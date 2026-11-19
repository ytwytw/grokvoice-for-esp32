# SPDX-License-Identifier: Apache-2.0
"""ESPHome microphone/control bridge and bounded, streamed WAV replies.

No device or cloud connection is opened at import. The caller supplies both clients.
"""
import asyncio
import base64
import logging
import math
import struct
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .audio import PCM
from .provider import safe_reason
from .reply_gain import apply_gain

_LOG = logging.getLogger(__name__)


class ReplyStream:
    """One bounded 16 kHz mono WAV, shared with HTTP reader threads."""
    def __init__(self, limit_bytes=32000 * 600):
        self.limit_bytes = limit_bytes
        self.condition = threading.Condition()
        self.data = bytearray(struct.pack('<4sI4s4sIHHIIHH4sI', b'RIFF', 0xffffffff,
            b'WAVE', b'fmt ', 16, 1, 1, 16000, 32000, 2, 16, b'data', 0xffffffff))
        self.closed = self.cancelled = False

    def append(self, pcm):
        if not isinstance(pcm, bytes) or len(pcm) % 2:
            raise ValueError('unaligned PCM')
        with self.condition:
            if self.closed:
                raise RuntimeError('retired reply')
            accepted = pcm[:self.limit_bytes - (len(self.data) - 44)]
            self.data.extend(accepted)
            self.closed = len(self.data) - 44 == self.limit_bytes
            self.condition.notify_all()
            return len(accepted)

    def finish(self, cancelled=False):
        with self.condition:
            self.closed = True
            self.cancelled = self.cancelled or cancelled
            self.condition.notify_all()

    def chunks(self):
        offset = 0
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.cancelled or len(self.data) > offset or self.closed)
                if self.cancelled:
                    raise ConnectionAbortedError('retired reply')
                if offset == len(self.data):
                    return
                chunk = bytes(self.data[offset:offset + 8192])
            offset += len(chunk)
            yield chunk


class Replies:
    def __init__(self, base_url, reply_seconds=600):
        if not math.isfinite(reply_seconds) or not 1 / 16000 <= reply_seconds <= (0xffffffff - 44) / 32000:
            raise ValueError('reply_seconds must be positive, finite and fit the WAV size range')
        self.reply_limit_bytes = int(reply_seconds * 16000) * 2
        self.base_url = base_url.rstrip('/')
        self.current = ('', None)

    def clear(self):
        if self.current[1] is not None:
            self.current[1].finish(cancelled=True)
        self.current = ('', None)

    def begin(self):
        self.clear()
        stream = ReplyStream(self.reply_limit_bytes)
        path = '/' + uuid.uuid4().hex + '.wav'
        self.current = (path, stream)
        return self.base_url + path, stream

    def get(self, path):
        key, data = self.current
        return data if key and path == key else None


def serve(replies, bind, port):
    """Start the LAN reply server; the caller must shutdown() and server_close()."""
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def do_GET(self):
            data = replies.get(self.path)
            if data is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', 'audio/wav')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Transfer-Encoding', 'chunked')
            self.end_headers()
            try:
                for chunk in data.chunks():
                    self.wfile.write(f'{len(chunk):x}\r\n'.encode() + chunk + b'\r\n')
                    self.wfile.flush()
                self.wfile.write(b'0\r\n\r\n')
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                self.close_connection = True

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer((bind, port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class Bridge:
    """All async methods run on one event loop; firmware supplies the wake pulse.

    Cloud input is disabled during generation and playback. A new wake is accepted
    only while idle. A button toggles the call; a long press starts a fresh context.
    """
    def __init__(self, device, replies, cloud_factory, *, session_seconds=300,
                 input_buffer_seconds=32, followup_seconds=8, reply_gain_db=0, tools_enabled=False):
        if not math.isfinite(session_seconds) or not 0 < session_seconds <= 300:
            raise ValueError('session_seconds must be in (0, 300]')
        if not math.isfinite(input_buffer_seconds) or not 8 <= input_buffer_seconds <= 300:
            raise ValueError('input_buffer_seconds must be in [8, 300]')
        if not math.isfinite(followup_seconds) or not 0 <= followup_seconds <= 60:
            raise ValueError('followup_seconds must be in [0, 60]')
        if not math.isfinite(reply_gain_db) or not -60 <= reply_gain_db <= 60:
            raise ValueError('reply_gain_db must be in [-60, 60]')
        self.device, self.replies, self.cloud_factory = device, replies, cloud_factory
        self.session_seconds, self.followup_seconds = session_seconds, followup_seconds
        self.reply_gain_db = reply_gain_db
        self.first_audio_timeout = session_seconds if tools_enabled else 15
        self.speech_grace_seconds = 6
        self.tx_limit, self.tx_bytes = int(input_buffer_seconds * 32000), 0
        self.tx = asyncio.Queue()
        self.lock = asyncio.Lock()
        self.task = self.wire = None
        self.active = self.closed = self.reply_playing = self.input_enabled = False
        self.muted = True  # Unknown initial hardware state is closed.
        self.epoch = 0
        self.reason = 'idle'

    def drain(self):
        while not self.tx.empty():
            self.tx.get_nowait()
        self.tx_bytes = 0

    def enqueue(self, data):
        while self.tx_bytes + len(data) > self.tx_limit:
            self.tx_bytes -= len(self.tx.get_nowait())
        self.tx.put_nowait(data)
        self.tx_bytes += len(data)

    def stop_reply(self, stop_audio=True):
        try:
            if self.reply_playing or (stop_audio and self.device.audio_playing):
                self.device.stop()
        except Exception as exc:
            _LOG.warning('device_stop_failed reason=%s', safe_reason(exc))
        finally:
            self.reply_playing = False
            self.replies.clear()

    async def reset(self, notify_idle=True, stop_audio=True):
        self.active = self.input_enabled = False
        self.epoch += 1
        self.stop_reply(stop_audio)
        self.drain()
        task, self.task = self.task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.reason = 'idle'
        if notify_idle and not self.closed:
            await self.device.state('idle')

    async def start_turn(self):
        if self.closed or self.muted or self.active:
            return
        await self.reset(notify_idle=False, stop_audio=False)
        self.active = self.input_enabled = True
        self.reason = 'listening'
        await self.device.state('listening')
        self.task = asyncio.create_task(self.turn(self.epoch))

    async def control(self, action, *, muted_at_request=False):
        async with self.lock:
            if action == 'stop':
                await self.reset()
            elif (muted_at_request or self.muted) and not self.closed:
                if action in ('wake', 'talk', 'new_context') and not self.active:
                    await self.device.state('idle')
            elif not self.closed and not self.muted:
                if action == 'wake':
                    if not self.active:
                        await self.start_turn()
                elif action == 'talk':
                    if self.active:
                        await self.reset()
                    else:
                        await self.start_turn()
                elif action == 'new_context':
                    await self.reset(notify_idle=False, stop_audio=self.active)
                    await self.start_turn()

    async def audio(self, data, data2=None):
        # Channel 0 is the firmware's AGC stream. Channel 1 is wake-only on device.
        async with self.lock:
            if self.closed or self.muted or not self.active or not self.input_enabled:
                return
            if not isinstance(data, bytes) or not data or len(data) % 2 or len(data) > 32000:
                await self.reset()
                self.reason = 'invalid_audio'
                return
            self.enqueue(data)

    async def close(self):
        self.closed = self.muted = True
        async with self.lock:
            await self.reset(notify_idle=False)

    async def turn(self, epoch):
        tasks, wire = [], None
        events = asyncio.Queue()
        response = stream = None
        output_bytes = 0
        generating = followup_guard = False

        def valid():
            return self.active and not self.closed and not self.muted and epoch == self.epoch

        async def receive():
            try:
                async for event in wire:
                    await events.put(event)
            except Exception as exc:
                events.put_nowait({'type': 'gateway.disconnected', 'exception': exc})
            finally:
                events.put_nowait({'type': 'gateway.disconnected'})

        async def upload():
            up = PCM(16000, 24000)
            try:
                while valid():
                    data = await self.tx.get()
                    self.tx_bytes -= len(data)
                    if valid() and self.input_enabled:
                        await wire.send_json(({'type': 'input_audio_buffer.append',
                            'audio': base64.b64encode(up.convert(data)).decode()},))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                events.put_nowait({'type': 'gateway.disconnected', 'exception': exc})

        async def played(response_id, seconds):
            try:
                await self.device.wait_playback_end(seconds + 15)
                events.put_nowait({'type': 'gateway.playback_done', 'response_id': response_id})
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                events.put_nowait({'type': 'gateway.playback_error', 'exception': exc})

        try:
            wire = await self.cloud_factory()
            self.wire = wire
            if not valid():
                return
            tasks = [asyncio.create_task(receive()), asyncio.create_task(upload())]
            deadline = time.monotonic() + self.speech_grace_seconds
            waiting = 'initial_speech'
            down = PCM(24000, 16000)
            while valid():
                now = time.monotonic()
                timeout = max(0, deadline - now) if deadline is not None else None
                try:
                    event = await asyncio.wait_for(events.get(), timeout)
                except asyncio.TimeoutError:
                    if waiting in ('initial_speech', 'followup'):
                        break
                    raise TimeoutError('reply timeout')
                if not valid():
                    break
                kind, now = event.get('type'), time.monotonic()
                if kind == 'input_audio_buffer.speech_started':
                    if generating or self.reply_playing or not self.input_enabled:
                        continue
                    followup_guard = False
                    deadline, waiting = now + self.session_seconds, 'speech'
                    self.reason = 'listening'
                    await self.device.state('listening_followup')
                elif kind in ('input_audio_buffer.speech_stopped', 'input_audio_buffer.committed'):
                    if generating or self.reply_playing or followup_guard:
                        continue
                    self.input_enabled = False
                    self.drain()
                    deadline, waiting = now + self.first_audio_timeout, 'first_audio'
                    self.reason = 'thinking'
                    await self.device.state('thinking')
                elif kind == 'response.created':
                    if followup_guard:
                        await wire.send_json(({'type': 'response.cancel'},))
                        continue
                    if response is not None:
                        raise RuntimeError('overlapping_response')
                    response = event['response']['id']
                    output_bytes, generating = 0, True
                    self.input_enabled = False
                    self.drain()
                    down = PCM(24000, 16000)
                    deadline, waiting = now + self.first_audio_timeout, 'first_audio'
                elif kind == 'response.output_audio.delta':
                    if not generating or event.get('response_id') != response:
                        continue
                    pcm = base64.b64decode(event['delta'], validate=True)
                    chunk = apply_gain(down.convert(pcm), self.reply_gain_db)
                    if not output_bytes:
                        url, stream = self.replies.begin()
                        accepted = stream.append(chunk)
                        await self.device.state('speaking')
                        if not valid():
                            break
                        self.device.play(url)
                        self.reply_playing = True
                        self.reason = 'speaking'
                    else:
                        accepted = stream.append(chunk)
                    output_bytes += accepted
                    deadline, waiting = now + self.session_seconds, 'generation'
                    if stream.closed:
                        # A capped reply drains accepted audio, then closes the call.
                        for task in tasks:
                            task.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
                        await wire.close()
                        self.wire = None
                        wire = None
                        await self.device.wait_playback_end(output_bytes / 32000 + 15)
                        break
                elif kind == 'response.done':
                    if response is None or event['response']['id'] != response:
                        continue
                    if event['response'].get('status') != 'completed' or not output_bytes:
                        raise RuntimeError('response_failed')
                    generating = False
                    stream.finish()
                    tasks.append(asyncio.create_task(played(response, output_bytes / 32000)))
                    deadline, waiting = None, 'playback'
                elif kind == 'gateway.playback_done' and event.get('response_id') == response:
                    self.reply_playing = False
                    self.replies.clear()
                    response = stream = None
                    output_bytes = 0
                    # Drop all stale input before reopening the follow-up microphone.
                    self.drain()
                    if not valid():
                        break
                    self.input_enabled = True
                    followup_guard = True
                    self.reason = 'followup'
                    await self.device.state('listening_followup')
                    deadline, waiting = time.monotonic() + self.followup_seconds, 'followup'
                elif kind in ('error', 'gateway.disconnected', 'gateway.playback_error'):
                    if isinstance(event.get('exception'), Exception):
                        raise event['exception']
                    raise RuntimeError({'error': 'provider_error',
                        'gateway.disconnected': 'provider_disconnected',
                        'gateway.playback_error': 'playback_failed'}[kind])
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.reason = 'turn_failed'
            self.active = self.input_enabled = False
            self.stop_reply()
            _LOG.warning('turn_failed reason=%s', safe_reason(exc))
            if not self.closed:
                await self.device.state('error')
                await asyncio.sleep(1)
        finally:
            self.input_enabled = False
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if wire is not None:
                try:
                    await asyncio.wait_for(wire.close(), 2)
                except Exception:
                    pass
            if self.wire is wire:
                self.wire = None
            if epoch == self.epoch:
                self.active = False
                self.stop_reply()
                self.drain()
                if not self.closed:
                    await self.device.state('idle')


class ESPDevice:
    def __init__(self, api, key, state_service):
        self.api, self.key, self.state_service = api, key, state_service
        self.media_state = None
        self.playing = self.awaiting_playback = False
        self.playback_done = asyncio.Event()

    @property
    def audio_playing(self):
        from aioesphomeapi import MediaPlayerState
        return self.media_state in (MediaPlayerState.PLAYING, MediaPlayerState.ANNOUNCING)

    async def state(self, state):
        await self.api.execute_service(self.state_service, {'state': state})

    def playback_state(self, state):
        from aioesphomeapi import MediaPlayerState
        self.media_state = state
        if not self.awaiting_playback:
            return
        if state in (MediaPlayerState.PLAYING, MediaPlayerState.ANNOUNCING):
            self.playing = True
        elif self.playing and state == MediaPlayerState.IDLE:
            self.playback_done.set()

    async def wait_playback_end(self, timeout):
        # Missing PLAYING -> IDLE feedback must never reopen the microphone on a timer.
        await asyncio.wait_for(self.playback_done.wait(), timeout)
        self.awaiting_playback = False

    def play(self, url):
        self.playing = False
        self.playback_done.clear()
        self.awaiting_playback = True
        self.api.media_player_command(self.key, media_url=url, announcement=True)

    def stop(self):
        from aioesphomeapi import MediaPlayerCommand
        self.api.media_player_command(self.key, command=MediaPlayerCommand.STOP, announcement=True)
        self.awaiting_playback = False


async def connect_forever(api_factory, bridge_factory, stop, retry_seconds=2):
    """Subscribe one encrypted API client per attempt; factories carry credentials."""
    from aioesphomeapi import BinarySensorInfo, BinarySensorState, MediaPlayerInfo, MediaPlayerEntityState
    from aioesphomeapi.model import VoiceAssistantEventType as Event
    while not stop.is_set():
        api, bridge = api_factory(), None
        lost = asyncio.Event()
        waiters, controls, unsubscribes = [], set(), []

        async def disconnected(expected):
            lost.set()
            if bridge is not None:
                bridge.closed = bridge.muted = True
                bridge.active = bridge.input_enabled = False
                bridge.stop_reply()

        try:
            await api.connect(on_stop=disconnected, login=True, log_errors=False)
            entities, services = await api.list_entities_services()
            players = [e for e in entities if isinstance(e, MediaPlayerInfo)]
            state_service = next((s for s in services if s.name == 'set_voice_state'), None)
            keys = {e.name: e.key for e in entities if isinstance(e, BinarySensorInfo)}
            required = {'Hardware Mute', 'Effective Mute', 'Talk Requested', 'Wake Requested',
                        'Stop Requested', 'New Context Requested'}
            if len(players) != 1 or state_service is None or not required <= keys.keys():
                raise RuntimeError('required_firmware_entities_missing')
            bridge = bridge_factory(ESPDevice(api, players[0].key, state_service))
            bridge.muted = True
            levels = {}
            mute_keys = (keys['Hardware Mute'], keys['Effective Mute'])
            actions = {keys[name]: action for name, action in (
                ('Talk Requested', 'talk'), ('Wake Requested', 'wake'),
                ('Stop Requested', 'stop'), ('New Context Requested', 'new_context'))}

            def control_done(task):
                controls.discard(task)
                if not task.cancelled() and task.exception() is not None:
                    _LOG.warning('device_control_failed reason=%s', safe_reason(task.exception()))
                    bridge.muted = True
                    bridge.input_enabled = False
                    lost.set()

            def state_changed(state):
                if isinstance(state, MediaPlayerEntityState) and state.key == players[0].key:
                    bridge.device.playback_state(state.state)
                elif isinstance(state, BinarySensorState):
                    previous = levels.get(state.key)
                    levels[state.key] = None if state.missing_state else state.state
                    action = None
                    if state.key in mute_keys:
                        bridge.muted = any(levels.get(key) is not False for key in mute_keys)
                        if bridge.muted:
                            # Shut the gate synchronously before the control task can be scheduled.
                            bridge.input_enabled = False
                            bridge.stop_reply()
                            action = 'stop'
                    elif previous is False and levels[state.key] is True:
                        action = actions.get(state.key)
                    if action is not None:
                        task = asyncio.create_task(bridge.control(action, muted_at_request=bridge.muted))
                        controls.add(task)
                        task.add_done_callback(control_done)

            api.subscribe_states(state_changed)

            async def start(*args):
                api.send_voice_assistant_event(Event.VOICE_ASSISTANT_RUN_START, {})
                api.send_voice_assistant_event(Event.VOICE_ASSISTANT_STT_START, {})
                return 0

            async def ended(abort):
                await bridge.control('stop')
                api.send_voice_assistant_event(Event.VOICE_ASSISTANT_RUN_END, {})

            unsubscribes.append(api.subscribe_voice_assistant(handle_start=start,
                handle_stop=ended, handle_audio=bridge.audio))
            _LOG.info('device_connected')
            waiters = [asyncio.create_task(e.wait()) for e in (stop, lost)]
            await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _LOG.warning('device_connect_failed reason=%s', safe_reason(exc))
        finally:
            for task in waiters + list(controls):
                task.cancel()
            await asyncio.gather(*waiters, *controls, return_exceptions=True)
            for unsubscribe in reversed(unsubscribes):
                try:
                    unsubscribe()
                except Exception as exc:
                    _LOG.warning('device_unsubscribe_failed reason=%s', safe_reason(exc))
            if bridge is not None:
                await bridge.close()
            try:
                await api.disconnect()
            except Exception:
                pass
        try:
            await asyncio.wait_for(stop.wait(), retry_seconds)
        except asyncio.TimeoutError:
            pass
