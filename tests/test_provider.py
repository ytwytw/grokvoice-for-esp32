# SPDX-License-Identifier: Apache-2.0
"""Offline auth and real pinned wire contracts; no account files or network."""
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
import io
import json
import os
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gateway import provider
from gateway.vendor import hermes_auth


ENV = {
    "TALK_PREFER_XAI_OAUTH": "true", "GROK_ACCOUNT_AUTHORIZED": "true",
    "GROK_EXPECTED_EMAIL": "owner@example.com", "HERMES_SOURCE": "/path/to/hermes-agent",
    "HERMES_PYTHON": "/path/to/hermes-python/bin/python3.14", "HERMES_HOME": "/path/to/hermes-data",
}
FORMAT = {"type": "audio/pcm", "rate": 24000}
ACK = {"type": "session.updated", "session": {"audio": {
    "input": {"format": FORMAT}, "output": {"format": FORMAT},
}}}
NORMALIZED_ACK = {"type": "session.updated", "session": {
    "turn_detection": {"type": "server_vad"},
    "tools": [{"type": "function", "function": {"name": "search_memory"}}],
}}


def identity(email="owner@example.com"):
    payload = base64.urlsafe_b64encode(json.dumps({"email": email}).encode()).decode().rstrip("=")
    return {"tokens": {"id_token": f"header.{payload}.signature"}}


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, ENV, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_no_keys_missing_consent_or_email(self):
        for name, value in (("XAI_API_KEY", "forbidden"), ("TALK_XAI_API_KEY", "forbidden"),
                            ("TALK_PREFER_XAI_OAUTH", "false"), ("GROK_ACCOUNT_AUTHORIZED", "false"),
                            ("GROK_EXPECTED_EMAIL", ""), ("HERMES_HOME", "relative")):
            with self.subTest(name=name), patch.dict(os.environ, {name: value}):
                with self.assertRaises(RuntimeError):
                    provider._configuration()

    def test_preflight_checks_imports_and_source_without_refresh(self):
        result = subprocess.CompletedProcess([], 0, provider.HERMES_REVISION, "")
        with patch.object(provider.subprocess, "run", return_value=result) as run, \
             patch.object(provider, "_auth_process", return_value={"ready": True}) as auth:
            provider.validate_environment()
            auth.assert_called_once_with(provider._configuration(), "preflight")
            self.assertEqual(run.call_count, 2)

    def test_preflight_wrong_revision(self):
        with patch.object(provider.subprocess, "run", return_value=SimpleNamespace(stdout="wrong")):
            with self.assertRaisesRegex(RuntimeError, "revision_mismatch"):
                provider.validate_environment()

    def test_child_diagnostics_never_escape(self):
        for result in (SimpleNamespace(returncode=1, stdout="private-token"),
                       SimpleNamespace(returncode=0, stdout='{"error":"private-token"}'),
                       SimpleNamespace(returncode=1, stdout='{"error":["private-token"]}')):
            with patch.object(provider.subprocess, "run", return_value=result):
                with self.assertRaisesRegex(RuntimeError, "^hermes_refresh_failed$"):
                    provider._auth_process(provider._configuration(), "refresh")

    def test_child_fixed_codes_and_private_environment(self):
        for code in hermes_auth.AUTH_ERROR_CODES:
            with self.subTest(code=code), patch.object(provider.subprocess, "run", return_value=
                    SimpleNamespace(returncode=1, stdout=json.dumps({"error": code}))):
                with self.assertRaisesRegex(RuntimeError, f"^{code}$"):
                    provider._auth_process(provider._configuration(), "refresh")
        with patch.dict(os.environ, {"ESPHOME_NOISE_PSK": "device-secret"}), \
             patch.object(provider.subprocess, "run", return_value=SimpleNamespace(
                 returncode=0, stdout='{"ready":true}')) as run:
            provider._auth_process(provider._configuration(), "preflight")
        args, kwargs = run.call_args
        self.assertNotIn(ENV["GROK_EXPECTED_EMAIL"], args[0])
        self.assertEqual(args[0][-1], "preflight")
        self.assertEqual(kwargs["env"]["GROK_EXPECTED_EMAIL"], ENV["GROK_EXPECTED_EMAIL"])
        self.assertNotIn("ESPHOME_NOISE_PSK", kwargs["env"])

    def test_mcp_header_variables_stay_out_of_auth_subprocess(self):
        result = SimpleNamespace(returncode=0, stdout='{"ready":true}')
        with patch.dict(os.environ, {"MANUALS_AUTH": "sample"}), \
             patch.object(provider.subprocess, "run", return_value=result) as run:
            provider._auth_process(provider._configuration(("MANUALS_AUTH",)), "preflight")
        self.assertNotIn("MANUALS_AUTH", run.call_args.kwargs["env"])

    def test_safe_reason_never_uses_arbitrary_exception_text(self):
        class PrivateError(RuntimeError):
            def __str__(self):
                raise AssertionError("must not stringify")
        for exc, code in ((RuntimeError("session_rejected"), "session_rejected"),
                          (RuntimeError("grok_handshake_403"), "grok_handshake_403"),
                          (RuntimeError("grok_handshake_999"), "RuntimeError"),
                          (RuntimeError("private-token"), "RuntimeError"),
                          (PrivateError("private-token"), "PrivateError")):
            with self.subTest(code=code):
                self.assertEqual(provider.safe_reason(exc), code)

    def test_refreshes_serialize_and_reuse_overlapping_request(self):
        provider._last_refresh = None
        started = threading.Event()
        calls = []
        def refresh(*args):
            calls.append(1)
            started.set()
            time.sleep(.05)
            return {"provider": "xai-oauth", "api_key": "fake-access"}
        with patch.object(provider, "_auth_process", side_effect=refresh), ThreadPoolExecutor(2) as pool:
            first = pool.submit(provider._credentials, provider._configuration())
            self.assertTrue(started.wait(1))
            second = pool.submit(provider._credentials, provider._configuration())
            self.assertEqual(first.result(), second.result())
        self.assertEqual(len(calls), 1)
        provider._last_refresh = None


class HermesShimTests(unittest.TestCase):
    def test_interpreter_and_missing_import_have_fixed_codes(self):
        with patch.object(sys, "version_info", (3, 12)):
            with self.assertRaisesRegex(RuntimeError, "^hermes_python_314_required$"):
                hermes_auth.run("preflight")
        with patch.object(sys, "version_info", (3, 14)), patch.dict(sys.modules, {"hermes_cli": None}):
            with self.assertRaisesRegex(RuntimeError, "^hermes_auth_import_failed$"):
                hermes_auth.run("preflight")

    def test_account_and_provider_checked_before_and_after_refresh(self):
        for mismatch in ("before_email", "after_email", "before_provider", "after_provider", "result_provider", None):
            with self.subTest(mismatch=mismatch):
                state = {"refreshed": False}
                def tokens():
                    wrong = mismatch == ("after_email" if state["refreshed"] else "before_email")
                    return identity("other@example.com" if wrong else "owner@example.com")
                def active():
                    wrong = mismatch == ("after_provider" if state["refreshed"] else "before_provider")
                    return "other" if wrong else "xai-oauth"
                def refresh(**kwargs):
                    self.assertEqual(kwargs, {})
                    state["refreshed"] = True
                    return {"provider": "other" if mismatch == "result_provider" else "xai-oauth", "api_key": "fake-access"}
                auth = SimpleNamespace(get_active_provider=active)
                xai = SimpleNamespace(_read_xai_oauth_tokens=tokens, resolve_xai_oauth_runtime_credentials=refresh)
                with patch.dict(sys.modules, {"hermes_cli": SimpleNamespace(auth=auth, auth_xai=xai),
                                              "hermes_cli.auth": auth, "hermes_cli.auth_xai": xai}), \
                     patch.object(sys, "version_info", (3, 14)):
                    self.assertEqual(hermes_auth.run("preflight"), {"ready": True})
                    self.assertFalse(state["refreshed"])
                    if mismatch:
                        with self.assertRaises(RuntimeError):
                            hermes_auth.run("refresh", "owner@example.com")
                    else:
                        self.assertEqual(hermes_auth.run("refresh", "owner@example.com")["provider"], "xai-oauth")

    def test_missing_or_malformed_identity_is_a_fixed_code(self):
        auth = SimpleNamespace(get_active_provider=lambda: "xai-oauth")
        payload = base64.urlsafe_b64encode(b'{"email":null}').decode()
        for token in ("", "invalid", "header.invalid.signature", f"header.{payload}.signature"):
            with self.subTest(token=token):
                xai = SimpleNamespace(_read_xai_oauth_tokens=lambda: {"tokens": {"id_token": token}})
                with self.assertRaisesRegex(RuntimeError, "^account_identity_unavailable$"):
                    hermes_auth._account(auth, xai, "owner@example.com")

    def test_shim_only_emits_allowlisted_error_codes(self):
        class AuthError(RuntimeError):
            def __init__(self, code):
                super().__init__("private-token")
                self.code = code
        for exc, expected in ((RuntimeError("account_mismatch"), "account_mismatch"),
                              (AuthError("xai_refresh_failed"), "xai_refresh_failed"),
                              (AuthError("private-token"), "hermes_auth_failed"),
                              (RuntimeError("private-token"), "hermes_auth_failed")):
            self.assertEqual(hermes_auth.error_code(exc), expected)

    def test_shim_main_uses_environment_and_suppresses_upstream_diagnostics(self):
        self.addCleanup(hermes_auth.logging.disable, hermes_auth.logging.root.manager.disable)
        def tokens():
            print("private-token")
            print("private-token", file=sys.stderr)
            return identity("other@example.com")
        auth = SimpleNamespace(get_active_provider=lambda: "xai-oauth")
        xai = SimpleNamespace(_read_xai_oauth_tokens=tokens,
                              resolve_xai_oauth_runtime_credentials=lambda: self.fail("must not refresh"))
        output = io.StringIO()
        with patch.dict(sys.modules, {"hermes_cli": SimpleNamespace(auth=auth, auth_xai=xai),
                                      "hermes_cli.auth": auth, "hermes_cli.auth_xai": xai}), \
             patch.object(sys, "version_info", (3, 14)), patch.object(sys, "argv", ["-c", "refresh"]), \
             patch.dict(os.environ, {"GROK_EXPECTED_EMAIL": "owner@example.com"}), \
             patch.object(sys, "stdout", output), self.assertRaises(SystemExit) as stopped:
            exec(provider._AUTH_SHIM.read_text(), {"__name__": "__main__"})
        self.assertEqual(stopped.exception.code, 1)
        self.assertEqual(json.loads(output.getvalue()), {"error": "account_mismatch"})


class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = patch.dict(os.environ, ENV, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.auth = patch.object(provider, "_credentials", return_value={"provider": "xai-oauth", "api_key": "fake-access"})
        self.auth.start()
        self.addCleanup(self.auth.stop)

    async def connect(self, events, connect_wait=False, connect_error=None):
        class Wire:
            closed = False
            async def connect(self, **kwargs):
                self.setup = kwargs["session_update"]
                if connect_error:
                    raise connect_error
                if connect_wait:
                    await asyncio.sleep(10)
            def __aiter__(self):
                return self
            async def __anext__(self):
                if events == "wait":
                    await asyncio.sleep(10)
                if not events:
                    raise StopAsyncIteration
                return events.pop(0)
            async def close(self):
                self.closed = True
        wire = Wire()
        with patch("talk_grok_realtime._GrokWireSession", return_value=wire), \
             patch.object(provider, "SETUP_TIMEOUT", .01), patch.object(provider, "CONNECT_TIMEOUT", .01):
            try:
                result = await provider.normal_oauth_cloud()
            except RuntimeError:
                self.assertTrue(wire.closed)
                raise
        return result

    async def test_ack_required_and_no_barge_in(self):
        wire = await self.connect([{"type": "session.created"}, ACK])
        session = wire.setup["session"]
        self.assertEqual(session["audio"]["input"]["turn_detection"], {
            "type": "server_vad", "create_response": True, "interrupt_response": False,
        })
        self.assertNotIn("transcription", session["audio"]["input"])
        self.assertNotIn("instructions", session)
        self.assertFalse(wire.closed)

    async def test_accepts_normalized_empty_and_flat_receipts(self):
        for receipt in (NORMALIZED_ACK, {"type": "session.updated", "session": {}},
                        {"type": "session.updated", "session": {
                            "input_audio_format": FORMAT, "output_audio_format": FORMAT}}):
            with self.subTest(receipt=receipt):
                self.assertFalse((await self.connect([receipt])).closed)

    async def test_rejects_missing_ack_bad_formats_errors_timeouts(self):
        bad_input = json.loads(json.dumps(ACK))
        bad_input["session"]["audio"]["input"]["format"]["rate"] = 16000
        bad_output = json.loads(json.dumps(ACK))
        bad_output["session"]["audio"]["output"]["format"]["type"] = "audio/opus"
        for events, connect_wait, reason in (([], False, "setup_disconnected"),
                    ([{"type": "error", "error": "private-data"}], False, "session_rejected"),
                    ([bad_input], False, "format_rejected"), ([bad_output], False, "format_rejected"),
                    ([{"type": "session.updated", "session": {"input_audio_format": "opus"}}], False, "format_rejected"),
                    ([{"type": "session.updated", "session": {"output_audio_format": None}}], False, "format_rejected"),
                    ("wait", False, "grok_session_setup_failed"), ([], True, "grok_session_setup_failed")):
            with self.subTest(events=events), self.assertRaisesRegex(RuntimeError, f"^{reason}$"):
                await self.connect(events, connect_wait)

    async def test_handshake_status_is_safe_and_wire_is_closed(self):
        from aiohttp import WSServerHandshakeError
        for status in (401, 403, 429, 503):
            exc = WSServerHandshakeError(SimpleNamespace(real_url="private-url"), (),
                                         status=status, message="private-token")
            with self.subTest(status=status), self.assertRaisesRegex(RuntimeError, f"^grok_handshake_{status}$"):
                await self.connect([], connect_error=exc)

    async def test_malformed_explicit_audio_is_rejected(self):
        for audio in (None, "bad", [], {"input": "bad"}, {"input": []},
                      {"output": None}, {"input": {"format": None}}):
            with self.subTest(audio=audio), self.assertRaisesRegex(RuntimeError, "^format_rejected$"):
                await self.connect([{"type": "session.updated", "session": {"audio": audio}}])

    async def test_setup_library_diagnostics_never_escape(self):
        with self.assertRaisesRegex(RuntimeError, "^grok_session_setup_failed$"):
            await self.connect([], connect_error=RuntimeError("private-token"))

    async def test_real_upstream_wire_over_fake_aiohttp(self):
        from talk_grok_realtime import _GrokWireSession
        class Kind(Enum):
            TEXT = 1
        sent = []
        connection = {}
        class Socket:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): connection["closed"] = True
            def __aiter__(self): return self
            async def __anext__(self): return SimpleNamespace(type=Kind.TEXT, data=json.dumps(ACK))
            async def send_json(self, message): sent.append(message)
        class HTTP:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            def ws_connect(self, url, **kwargs):
                connection.update(url=url, **kwargs)
                return Socket()
        fake = SimpleNamespace(ClientSession=HTTP, WSMsgType=Kind)
        def factory(**kwargs): return _GrokWireSession(aiohttp_module=fake, **kwargs)
        tools = [{"type": "web_search"}, {"type": "x_search"}, {
            "type": "mcp", "server_url": "https://mcp.example.com/mcp", "server_label": "manuals",
            "allowed_tools": ["search_manual"], "headers": {"Authorization": "sample header"},
        }]
        with patch("talk_grok_realtime._GrokWireSession", side_effect=factory):
            wire = await provider.normal_oauth_cloud(instructions="Speak briefly", tools=tools)
            await wire.send_json(({"type": "input_audio_buffer.append", "audio": "AAAA"},))
            self.assertEqual((await wire.__anext__())["type"], "session.updated")
            await wire.close()
        self.assertEqual(connection["url"], "wss://api.x.ai/v1/realtime?model=grok-voice-latest")
        self.assertEqual(connection["headers"], {"Authorization": "Bearer fake-access"})
        self.assertEqual(sent[0]["type"], "session.update")
        self.assertEqual(sent[0]["session"]["tools"], tools)
        self.assertEqual(sent[1]["type"], "input_audio_buffer.append")
        self.assertTrue(connection["closed"])
        self.assertIsNone(wire._auth_token)


if __name__ == "__main__":
    unittest.main()
