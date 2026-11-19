# SPDX-License-Identifier: Apache-2.0
"""Offline device/wire tests. Loopback HTTP is the only socket used."""
import asyncio
import base64
import http.client
import struct
import unittest
from urllib.parse import urlsplit

from aioesphomeapi import (BinarySensorInfo, BinarySensorState, MediaPlayerEntityState,
                          MediaPlayerInfo, MediaPlayerState, UserService)
from gateway.audio import PCM
from gateway.bridge import Bridge, Replies, connect_forever, serve
from gateway.reply_gain import CEILING, apply_gain


async def eventually(predicate):
    for _ in range(500):
        if predicate():
            return
        await asyncio.sleep(.001)
    raise AssertionError('condition did not become true')


class FakeWire:
    def __init__(self):
        self.events = asyncio.Queue()
        self.sent = []
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        event = await self.events.get()
        if event is None:
            raise StopAsyncIteration
        if isinstance(event, Exception):
            raise event
        return event

    async def send_json(self, events):
        self.sent.extend(events)

    async def close(self):
        self.closed = True
        self.events.put_nowait(None)

    def emit(self, kind, **fields):
        self.events.put_nowait({'type': kind, **fields})

    def reply(self, response_id='r1', samples=2400):
        self.emit('response.created', response={'id': response_id})
        self.emit('response.output_audio.delta', response_id=response_id,
                  delta=base64.b64encode(struct.pack('<h', 2000) * samples).decode())
        self.emit('response.done', response={'id': response_id, 'status': 'completed'})


class FakeDevice:
    def __init__(self):
        self.states, self.urls = [], []
        self.stops = 0
        self.audio_playing = False
        self.playback_done = asyncio.Event()

    async def state(self, state):
        self.states.append(state)

    def play(self, url):
        self.urls.append(url)
        self.audio_playing = True
        self.playback_done.clear()

    def stop(self):
        self.stops += 1
        self.audio_playing = False

    async def wait_playback_end(self, timeout):
        await asyncio.wait_for(self.playback_done.wait(), timeout)
        self.audio_playing = False


CONTROL_NAMES = ('Hardware Mute', 'Effective Mute', 'Talk Requested', 'Wake Requested',
                 'Stop Requested', 'New Context Requested')


class FakeAPI:
    """Uses the pinned aioesphomeapi models and its subscription return contracts."""
    def __init__(self):
        self.keys = {name: i + 1 for i, name in enumerate(CONTROL_NAMES)}
        self.player_key = 50
        self.commands, self.states, self.events = [], [], []
        self.on_state = self.on_stop = None
        self.handlers = {}
        self.connected = self.disconnected = self.unsubscribed = False

    async def connect(self, *, on_stop, login, log_errors):
        self.connected = True
        self.on_stop = on_stop

    async def list_entities_services(self):
        return ([MediaPlayerInfo(key=self.player_key)] +
                [BinarySensorInfo(name=name, key=key) for name, key in self.keys.items()],
                [UserService(name='set_voice_state', key=1)])

    def subscribe_states(self, callback):
        self.on_state = callback
        return None

    def subscribe_voice_assistant(self, **handlers):
        self.handlers = handlers
        def unsubscribe():
            self.unsubscribed = True
        return unsubscribe

    async def execute_service(self, service, data):
        self.states.append(data['state'])

    def media_player_command(self, key, **kwargs):
        self.commands.append(kwargs)

    def send_voice_assistant_event(self, event, data):
        self.events.append(event)

    async def disconnect(self):
        self.disconnected = True

    def sensor(self, name, state, *, missing=False):
        self.on_state(BinarySensorState(key=self.keys[name], state=state, missing_state=missing))

    def unmute(self):
        self.sensor('Hardware Mute', False)
        self.sensor('Effective Mute', False)

    def pulse(self, name):
        self.sensor(name, False)
        self.sensor(name, True)
        self.sensor(name, False)

    def player(self, state):
        self.on_state(MediaPlayerEntityState(key=self.player_key, state=state))


class AudioTests(unittest.TestCase):
    def test_pcm_streaming_resampler_keeps_state(self):
        pcm = struct.pack('<hhhhhh', 0, 1000, 2000, 3000, 4000, 5000)
        one = PCM(16000, 24000).convert(pcm)
        split = PCM(16000, 24000)
        self.assertEqual(one, split.convert(pcm[:6]) + split.convert(pcm[6:]))
        self.assertRaises(ValueError, split.convert, b'\x00')

    def test_gain_ceiling_and_invalid_gain(self):
        pcm = struct.pack('<hhhh', 32767, -32768, 1000, -1000)
        self.assertEqual(struct.unpack('<hhhh', apply_gain(pcm, 0)), (CEILING, -CEILING, 1000, -1000))
        self.assertRaises(ValueError, apply_gain, pcm, float('nan'))

    def test_reply_cap_and_retirement(self):
        replies = Replies('http://example.invalid', reply_seconds=1 / 16000)
        url, stream = replies.begin()
        self.assertEqual(stream.append(b'\x01\x00' * 2), 2)
        self.assertTrue(stream.closed)
        data = b''.join(stream.chunks())
        self.assertEqual(data[:4], b'RIFF')
        self.assertEqual(len(data), 46)
        replies.clear()
        self.assertIsNone(replies.get(urlsplit(url).path))
        with self.assertRaises(ConnectionAbortedError):
            next(stream.chunks())
        self.assertRaises(ValueError, Replies, 'http://example.invalid', float('inf'))

    def test_actual_http_chunked_wav_stream(self):
        replies = Replies('http://example.invalid')
        url, stream = replies.begin()
        server = serve(replies, '127.0.0.1', 0)
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=2)
        try:
            conn.request('GET', urlsplit(url).path)
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.getheader('Transfer-Encoding'), 'chunked')
            self.assertEqual(response.getheader('Cache-Control'), 'no-store')
            self.assertEqual(response.read(44)[:4], b'RIFF')
            # The header arrives before generation is complete.
            self.assertFalse(stream.closed)
            stream.append(b'\x01\x00' * 100)
            stream.finish()
            self.assertEqual(response.read(), b'\x01\x00' * 100)
            conn.request('GET', '/missing.wav')
            missing = conn.getresponse()
            self.assertEqual(missing.status, 404)
            missing.read()
        finally:
            replies.clear()
            conn.close()
            server.shutdown()
            server.server_close()


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.device, self.wire = FakeDevice(), FakeWire()
        self.factory_calls = 0
        async def cloud():
            self.factory_calls += 1
            return self.wire
        self.bridge = Bridge(self.device, Replies('http://example.invalid'), cloud)

    async def asyncTearDown(self):
        await self.bridge.close()

    async def start(self):
        self.bridge.muted = False
        await self.bridge.control('talk')
        await eventually(lambda: self.bridge.wire is self.wire)

    async def test_unknown_mute_and_idle_never_open_cloud(self):
        await self.bridge.control('talk')
        await self.bridge.control('wake')
        await self.bridge.audio(b'\x01\x00' * 160)
        self.assertEqual(self.factory_calls, 0)
        self.bridge.muted = False
        await self.bridge.audio(b'\x01\x00' * 160)
        self.assertEqual(self.factory_calls, 0)
        self.assertEqual(self.bridge.tx_bytes, 0)

    async def test_idle_wake_accepts_its_own_chime(self):
        self.bridge.muted = False
        self.device.audio_playing = True
        await self.bridge.control('wake')
        await eventually(lambda: self.factory_calls == 1)
        self.assertTrue(self.bridge.active)
        self.assertEqual(self.device.states[-1], 'listening')
        self.assertEqual(self.device.stops, 0)

    async def test_idle_new_context_keeps_its_chime(self):
        self.bridge.muted = False
        self.device.audio_playing = True
        await self.bridge.control('new_context')
        await eventually(lambda: self.factory_calls == 1)
        self.assertTrue(self.bridge.active)
        self.assertEqual(self.device.stops, 0)

    async def test_rejected_idle_triggers_release_reservation_and_preserve_mute(self):
        for action in ('wake', 'talk', 'new_context'):
            self.device.states.clear()
            await self.bridge.control(action)
            self.assertEqual(self.device.states, ['idle'])
            self.assertTrue(self.bridge.muted)
            self.assertFalse(self.bridge.active)
        await self.bridge.close()
        self.device.states.clear()
        await self.bridge.control('wake')
        self.assertFalse(self.device.states)
        self.assertEqual(self.factory_calls, 0)

    async def test_rejected_active_wake_preserves_current_state(self):
        await self.start()
        self.device.states.clear()
        await self.bridge.control('wake')
        self.bridge.muted = True
        await self.bridge.control('wake')
        self.assertFalse(self.device.states)
        self.assertTrue(self.bridge.active)
        self.assertEqual(self.factory_calls, 1)

    async def test_upload_start_and_after_close(self):
        await self.start()
        await self.bridge.audio(b'\x01\x00' * 160)
        await eventually(lambda: bool(self.wire.sent))
        self.assertEqual(self.wire.sent[0]['type'], 'input_audio_buffer.append')
        self.assertGreater(len(base64.b64decode(self.wire.sent[0]['audio'])), 320)
        await self.bridge.close()
        count = len(self.wire.sent)
        await self.bridge.audio(b'\x01\x00' * 160)
        self.assertEqual(len(self.wire.sent), count)
        self.assertTrue(self.wire.closed)

    async def test_button_ends_and_long_press_creates_fresh_context(self):
        await self.start()
        await self.bridge.control('talk')
        self.assertFalse(self.bridge.active)
        self.assertTrue(self.wire.closed)
        self.wire = FakeWire()
        await self.bridge.control('new_context')
        await eventually(lambda: self.factory_calls == 2)
        self.assertTrue(self.bridge.active)
        old = self.wire
        self.wire = FakeWire()
        await self.bridge.control('new_context')
        await eventually(lambda: self.factory_calls == 3)
        self.assertTrue(old.closed)

    async def test_idle_only_wake_no_speech_bargein_and_followup_after_playback(self):
        self.bridge.followup_seconds = .05
        await self.start()
        self.wire.reply()
        await eventually(lambda: bool(self.device.urls))
        await self.bridge.control('wake')
        self.assertEqual(self.factory_calls, 1)
        self.wire.emit('input_audio_buffer.speech_started')
        await self.bridge.audio(b'\x01\x00' * 160)
        await asyncio.sleep(.07)
        self.assertTrue(self.bridge.active)  # Generation completion did not start follow-up.
        self.assertTrue(self.bridge.reply_playing)
        self.assertFalse(self.bridge.input_enabled)
        self.assertEqual(self.device.stops, 0)
        self.assertFalse(any(e['type'] == 'input_audio_buffer.append' for e in self.wire.sent))
        self.device.playback_done.set()
        await eventually(lambda: self.bridge.reason == 'followup')
        self.assertFalse(any(e['type'] == 'input_audio_buffer.clear' for e in self.wire.sent))
        await eventually(lambda: not self.bridge.active)
        self.assertTrue(self.wire.closed)

    async def test_followup_reuses_session_and_requires_new_speech(self):
        await self.start()
        self.wire.reply()
        await eventually(lambda: bool(self.device.urls))
        self.device.playback_done.set()
        await eventually(lambda: self.bridge.reason == 'followup')
        self.wire.emit('response.created', response={'id': 'speculative'})
        await eventually(lambda: any(e['type'] == 'response.cancel' for e in self.wire.sent))
        self.wire.emit('input_audio_buffer.speech_started')
        self.wire.emit('input_audio_buffer.speech_stopped')
        self.wire.reply('r2')
        await eventually(lambda: len(self.device.urls) == 2)
        self.assertEqual(self.factory_calls, 1)

    async def test_cloud_error_stops_playback_and_retires_url(self):
        await self.start()
        self.wire.reply()
        await eventually(lambda: bool(self.device.urls))
        path = urlsplit(self.device.urls[0]).path
        with self.assertLogs('gateway.bridge', level='WARNING') as logs:
            self.wire.emit('error', error={'message': 'private payload'})
            await eventually(lambda: not self.bridge.active)
        self.assertEqual(logs.output, ['WARNING:gateway.bridge:turn_failed reason=provider_error'])
        self.assertIsNone(self.bridge.replies.get(path))
        self.assertEqual(self.device.stops, 1)

    async def test_runtime_failures_log_only_fixed_codes_or_exception_classes(self):
        for failure, reason in ((RuntimeError('format_rejected'), 'format_rejected'),
                                (RuntimeError('private token payload'), 'RuntimeError'),
                                (ConnectionResetError('private transport address'), 'ConnectionResetError')):
            with self.subTest(reason=reason):
                async def broken_cloud():
                    raise failure
                self.bridge.cloud_factory = broken_cloud
                self.bridge.muted = False
                with self.assertLogs('gateway.bridge', level='WARNING') as logs:
                    await self.bridge.control('talk')
                    await eventually(lambda: not self.bridge.active)
                self.assertEqual(logs.output, [f'WARNING:gateway.bridge:turn_failed reason={reason}'])
                await self.bridge.control('stop')

    async def test_wire_transport_failure_keeps_exception_class_only(self):
        await self.start()
        with self.assertLogs('gateway.bridge', level='WARNING') as logs:
            self.wire.events.put_nowait(ConnectionResetError('private transport address'))
            await eventually(lambda: not self.bridge.active)
        self.assertEqual(logs.output, ['WARNING:gateway.bridge:turn_failed reason=ConnectionResetError'])

    async def test_upload_and_playback_failures_keep_exception_class_only(self):
        for operation, reason in (('upload', 'ConnectionError'), ('playback', 'TimeoutError')):
            with self.subTest(operation=operation):
                self.wire = FakeWire()
                await self.start()
                async def broken_upload(events):
                    raise ConnectionError('private transport address')
                async def broken_playback(timeout):
                    raise TimeoutError('private playback address')
                with self.assertLogs('gateway.bridge', level='WARNING') as logs:
                    if operation == 'upload':
                        self.wire.send_json = broken_upload
                        await self.bridge.audio(b'\x01\x00' * 160)
                    else:
                        self.device.wait_playback_end = broken_playback
                        self.wire.reply()
                    await eventually(lambda: not self.bridge.active)
                self.assertEqual(logs.output, [f'WARNING:gateway.bridge:turn_failed reason={reason}'])
                await self.bridge.control('stop')

    async def test_error_indicator_reverts_to_idle(self):
        await self.start()
        task = self.bridge.task
        with self.assertLogs('gateway.bridge', level='WARNING'):
            self.wire.emit('error', error={'message': 'private payload'})
            await eventually(lambda: not self.bridge.active)
            self.assertEqual(self.device.states[-1], 'error')
            await asyncio.wait_for(task, 2)
        self.assertEqual(self.device.states[-1], 'idle')

    async def test_new_turn_cancels_error_indicator_without_stale_idle(self):
        await self.start()
        with self.assertLogs('gateway.bridge', level='WARNING'):
            self.wire.emit('error', error={'message': 'private payload'})
            await eventually(lambda: not self.bridge.active)
        self.wire = FakeWire()
        await self.bridge.control('talk')
        await eventually(lambda: self.factory_calls == 2)
        self.assertTrue(self.bridge.active)
        self.assertEqual(self.device.states[-1], 'listening')

    async def test_bounded_microphone_queue_drops_oldest(self):
        for n in range(40):
            self.bridge.enqueue(bytes([n, 0]) * 16000)
        self.assertEqual(self.bridge.tx_bytes, 32 * 32000)
        self.assertEqual(self.bridge.tx.get_nowait()[:2], bytes([8, 0]))

    async def test_invalid_pcm_fails_closed(self):
        await self.start()
        await self.bridge.audio(b'\x00')
        self.assertFalse(self.bridge.active)
        self.assertEqual(self.bridge.reason, 'invalid_audio')

    async def test_stop_command_failure_still_retires_reply_and_wire(self):
        await self.start()
        self.wire.reply()
        await eventually(lambda: bool(self.device.urls))
        path = urlsplit(self.device.urls[0]).path
        def broken_stop():
            raise RuntimeError('private device details')
        self.device.stop = broken_stop
        with self.assertLogs('gateway.bridge', level='WARNING') as logs:
            await self.bridge.control('stop')
        self.assertFalse(self.bridge.active)
        self.assertFalse(self.bridge.input_enabled)
        self.assertIsNone(self.bridge.replies.get(path))
        self.assertTrue(self.wire.closed)
        self.assertEqual(self.bridge.tx_bytes, 0)
        self.assertEqual(logs.output, ['WARNING:gateway.bridge:device_stop_failed reason=RuntimeError'])
        self.device.audio_playing = False


class ConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.api, self.stop = FakeAPI(), asyncio.Event()
        self.wires, self.bridges = [], []
        async def cloud():
            wire = FakeWire()
            self.wires.append(wire)
            return wire
        def bridge(device):
            value = Bridge(device, Replies('http://example.invalid'), cloud)
            self.bridges.append(value)
            return value
        self.runner = asyncio.create_task(connect_forever(lambda: self.api, bridge, self.stop, .01))
        await eventually(lambda: bool(self.api.handlers))

    async def asyncTearDown(self):
        self.stop.set()
        await self.runner

    async def test_attach_native_api_audio_and_controls(self):
        await self.api.handlers['handle_start']('conversation', 0, None, None)
        self.assertEqual(len(self.api.events), 2)
        self.api.pulse('Talk Requested')
        await asyncio.sleep(.01)
        self.assertFalse(self.wires)  # Mute state unknown.
        self.api.unmute()
        await asyncio.sleep(.01)
        await self.api.handlers['handle_audio'](b'\x01\x00' * 160, None)
        self.assertFalse(self.wires)  # Unmute alone never starts a call.
        self.api.pulse('Wake Requested')
        await eventually(lambda: bool(self.wires))
        await self.api.handlers['handle_audio'](b'\x01\x00' * 160, None)
        await eventually(lambda: bool(self.wires[0].sent))
        self.api.pulse('Stop Requested')
        await eventually(lambda: not self.bridges[0].active)
        self.assertTrue(self.wires[0].closed)

    async def test_mute_missing_state_and_disconnect_fail_closed(self):
        self.api.unmute()
        await asyncio.sleep(.01)
        self.api.pulse('Talk Requested')
        await eventually(lambda: bool(self.wires))
        bridge, wire = self.bridges[0], self.wires[0]
        wire.reply()
        await eventually(lambda: bool(self.api.commands))
        self.api.player(MediaPlayerState.ANNOUNCING)
        self.api.sensor('Effective Mute', False, missing=True)
        self.assertTrue(bridge.muted)
        self.assertFalse(bridge.input_enabled)
        self.assertTrue(any('command' in c for c in self.api.commands))
        await eventually(lambda: wire.closed)
        self.api.unmute()
        await asyncio.sleep(.01)
        self.api.pulse('Talk Requested')
        await eventually(lambda: len(self.wires) == 2)
        await self.api.on_stop(False)
        self.assertTrue(bridge.muted)
        self.assertTrue(bridge.closed)
        await self.api.handlers['handle_audio'](b'\x01\x00' * 160, None)
        self.stop.set()
        await self.runner
        self.assertTrue(self.wires[-1].closed)
        self.assertTrue(self.api.disconnected)
        self.assertTrue(self.api.unsubscribed)

    async def test_player_requires_actual_playing_to_idle_transition(self):
        device = self.bridges[0].device
        device.play('http://example.invalid/reply.wav')
        self.api.player(MediaPlayerState.IDLE)
        with self.assertRaises(asyncio.TimeoutError):
            await device.wait_playback_end(.01)
        self.api.player(MediaPlayerState.ANNOUNCING)
        self.api.player(MediaPlayerState.IDLE)
        await device.wait_playback_end(.01)

    async def test_disconnect_with_broken_command_cleans_up(self):
        self.api.unmute()
        await asyncio.sleep(.01)
        self.api.pulse('Talk Requested')
        await eventually(lambda: bool(self.wires))
        self.wires[0].reply()
        await eventually(lambda: bool(self.api.commands))
        def broken_command(*args, **kwargs):
            raise RuntimeError('private disconnected address')
        self.api.media_player_command = broken_command
        self.stop.set()
        with self.assertLogs('gateway.bridge', level='WARNING') as logs:
            await self.api.on_stop(False)
            await self.runner
        self.assertTrue(self.api.disconnected)
        self.assertTrue(self.api.unsubscribed)
        self.assertTrue(self.wires[0].closed)
        self.assertEqual(self.bridges[0].replies.current, ('', None))
        self.assertFalse(any('private' in entry for entry in logs.output))


class ConnectionFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_connect_failures_log_safe_reasons(self):
        for missing_entities in (False, True):
            with self.subTest(missing_entities=missing_entities):
                api, stop = FakeAPI(), asyncio.Event()
                async def broken_connect(**kwargs):
                    stop.set()
                    raise OSError('private device address')
                async def no_entities():
                    stop.set()
                    return [], []
                if missing_entities:
                    api.list_entities_services = no_entities
                else:
                    api.connect = broken_connect
                with self.assertLogs('gateway.bridge', level='WARNING') as logs:
                    await connect_forever(lambda: api, None, stop)
                reason = 'required_firmware_entities_missing' if missing_entities else 'OSError'
                self.assertEqual(logs.output, [f'WARNING:gateway.bridge:device_connect_failed reason={reason}'])
                self.assertTrue(api.disconnected)


if __name__ == '__main__':
    unittest.main()
