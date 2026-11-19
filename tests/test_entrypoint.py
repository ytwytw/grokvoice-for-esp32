# SPDX-License-Identifier: Apache-2.0
"""Exercise the actual service entry point with a fake client and real HTTP server."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gateway.__main__ import run
from gateway.bridge import Replies, serve


class EntrypointTests(unittest.IsolatedAsyncioTestCase):
    async def test_service_constructs_encrypted_client_and_cleans_http(self):
        servers = []
        api_client = object()
        fake_wire = object()

        async def cloud():
            return fake_wire

        def start_http(replies, bind, port):
            server = serve(replies, bind, port)
            servers.append(server)
            return server

        async def connection(api_factory, bridge_factory, stop):
            self.assertIs(api_factory(), api_client)
            device = SimpleNamespace(audio_playing=False)
            bridge = bridge_factory(device)
            self.assertIs(await bridge.cloud_factory(), fake_wire)
            self.assertTrue(bridge.muted)
            self.assertEqual(bridge.followup_seconds, 8)
            self.assertIsInstance(bridge.replies, Replies)

        args = SimpleNamespace(host='voice-device.local', base_url='http://gateway.local:8765',
                               bind='127.0.0.1', http_port=0)
        loop = asyncio.get_running_loop()
        with patch('aioesphomeapi.APIClient', return_value=api_client) as factory:
            with patch('gateway.provider.normal_oauth_cloud', cloud), \
                 patch('gateway.bridge.serve', start_http), \
                 patch('gateway.bridge.connect_forever', connection), \
                 patch.object(loop, 'add_signal_handler'), \
                 patch.dict('os.environ', {'ESPHOME_NOISE_PSK': 'fake-local-key'}):
                await run(args)
        factory.assert_called_once_with('voice-device.local', 6053, password=None,
                                        noise_psk='fake-local-key', client_info='grokvoice')
        self.assertEqual(servers[0].socket.fileno(), -1)

    async def test_actual_service_device_to_wire_to_streamed_reply(self):
        import http.client
        import signal
        from urllib.parse import urlsplit
        from aioesphomeapi import MediaPlayerState
        from test_bridge import FakeAPI, FakeWire, eventually

        api, wire, servers, signals = FakeAPI(), FakeWire(), [], {}

        async def cloud():
            return wire

        def start_http(replies, bind, port):
            server = serve(replies, bind, port)
            servers.append(server)
            return server

        def fetch(path):
            connection = http.client.HTTPConnection('127.0.0.1', servers[0].server_port, timeout=2)
            try:
                connection.request('GET', path)
                response = connection.getresponse()
                return response.status, response.read()
            finally:
                connection.close()

        args = SimpleNamespace(host='voice-device.local', base_url='http://gateway.local:8765',
                               bind='127.0.0.1', http_port=0)
        loop = asyncio.get_running_loop()
        with patch('aioesphomeapi.APIClient', return_value=api), \
             patch('gateway.provider.normal_oauth_cloud', cloud), \
             patch('gateway.bridge.serve', start_http), \
             patch.object(loop, 'add_signal_handler', side_effect=lambda sig, cb: signals.update({sig: cb})), \
             patch.dict('os.environ', {'ESPHOME_NOISE_PSK': 'fake-local-key'}):
            task = asyncio.create_task(run(args))
            try:
                await eventually(lambda: bool(api.handlers))
                api.unmute()
                await asyncio.sleep(.01)
                api.pulse('Talk Requested')
                await eventually(lambda: 'listening' in api.states)
                await api.handlers['handle_audio'](b'\x01\x00' * 160, None)
                await eventually(lambda: bool(wire.sent))
                self.assertEqual(wire.sent[0]['type'], 'input_audio_buffer.append')
                wire.reply()
                await eventually(lambda: any('media_url' in command for command in api.commands))
                url = next(command['media_url'] for command in api.commands if 'media_url' in command)
                status, wav = await asyncio.to_thread(fetch, urlsplit(url).path)
                self.assertEqual(status, 200)
                self.assertEqual(wav[:4], b'RIFF')
                self.assertGreater(len(wav), 44)
                api.player(MediaPlayerState.ANNOUNCING)
                api.player(MediaPlayerState.IDLE)
                await eventually(lambda: 'listening_followup' in api.states)
            finally:
                signals[signal.SIGTERM]()
                await asyncio.wait_for(task, 3)
        self.assertTrue(api.disconnected)
        self.assertTrue(wire.closed)
        self.assertEqual(servers[0].socket.fileno(), -1)
