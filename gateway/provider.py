# SPDX-License-Identifier: Apache-2.0
"""Own-account Hermes OAuth → pinned Grok realtime wire, with no key fallback."""
import asyncio
import contextlib
import json
import os
from pathlib import Path
import subprocess
import threading
import time

from .vendor.hermes_auth import AUTH_ERROR_CODES

HERMES_REVISION = "9ffa7dff23726d8daa8b3e167b20a5fabc2e04ef"
SETUP_TIMEOUT = 20
CONNECT_TIMEOUT = 35
_REFRESH_LOCK = threading.Lock()
_last_refresh = None
_AUTH_SHIM = Path(__file__).with_name("vendor") / "hermes_auth.py"
_REASON_CODES = AUTH_ERROR_CODES | {
    "normal_oauth_required", "own_account_authorization_required", "expected_email_required",
    "hermes_source_absolute_path_required", "hermes_python_absolute_path_required",
    "hermes_home_absolute_path_required", "hermes_revision_mismatch",
    "provider_dependencies_unavailable_or_modified", "hermes_preflight_failed",
    "hermes_refresh_failed", "account_or_provider_mismatch", "session_rejected",
    "format_rejected", "setup_disconnected", "grok_session_setup_failed",
    "overlapping_response", "response_failed", "provider_error", "provider_disconnected",
    "playback_failed", "required_firmware_entities_missing",
} | {f"grok_handshake_{status}" for status in range(100, 600)}


def safe_reason(exc):
    """Only fixed project codes or exception class names may enter logs."""
    if type(exc) is RuntimeError and len(exc.args) == 1 and isinstance(exc.args[0], str):
        code = exc.args[0]
        if code in _REASON_CODES:
            return code
    return type(exc).__name__


def _configuration(header_vars=()):
    if os.environ.get("TALK_PREFER_XAI_OAUTH") != "true" or any(
        os.environ.get(key) for key in ("XAI_API_KEY", "TALK_XAI_API_KEY")
    ):
        raise RuntimeError("normal_oauth_required")
    if os.environ.get("GROK_ACCOUNT_AUTHORIZED") != "true":
        raise RuntimeError("own_account_authorization_required")
    email = os.environ.get("GROK_EXPECTED_EMAIL", "").strip()
    if "@" not in email or any(c.isspace() for c in email):
        raise RuntimeError("expected_email_required")
    paths = []
    for name in ("HERMES_SOURCE", "HERMES_PYTHON", "HERMES_HOME"):
        path = Path(os.environ.get(name, ""))
        if not os.environ.get(name) or not path.is_absolute():
            raise RuntimeError(f"{name.lower()}_absolute_path_required")
        paths.append(path)
    return (*paths, email, header_vars)


def _auth_process(config, mode):
    source, python, home, email, header_vars = config
    env = os.environ.copy()
    for name in ("ESPHOME_NOISE_PSK", *header_vars):
        env.pop(name, None)
    env.update(HERMES_HOME=str(home), GROK_EXPECTED_EMAIL=email)
    try:
        result = subprocess.run(
            [str(python), "-c", _AUTH_SHIM.read_text(), mode],
            cwd=source, env=env, capture_output=True, text=True,
            timeout=15 if mode == "preflight" else 70, check=False,
        )
        data = json.loads(result.stdout)
        if isinstance(data, dict) and isinstance(data.get("error"), str) and data["error"] in AUTH_ERROR_CODES:
            raise RuntimeError(data["error"])
        if result.returncode or not isinstance(data, dict) or "error" in data:
            raise ValueError("auth_failed")
        return data
    except (OSError, ValueError, subprocess.SubprocessError):
        raise RuntimeError(f"hermes_{mode}_failed") from None


def validate_environment(header_vars=()):
    """Local config, pinned source and full auth/wire imports; never load tokens."""
    config = _configuration(header_vars)
    try:
        import aiohttp
        import httpx
        from talk_grok_realtime import _GrokWireSession, build_session_update
        from talk_realtime import SessionSetup
        assert all((aiohttp.ClientSession, httpx.Client, _GrokWireSession,
                    build_session_update, SessionSetup))
        revision = subprocess.run(
            ["git", "-C", str(config[0]), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
        if revision != HERMES_REVISION:
            raise RuntimeError("hermes_revision_mismatch")
        subprocess.run(
            ["git", "-C", str(config[0]), "diff", "--quiet", "HEAD", "--"],
            capture_output=True, timeout=15, check=True,
        )
    except (ImportError, OSError, subprocess.SubprocessError):
        raise RuntimeError("provider_dependencies_unavailable_or_modified") from None
    if _auth_process(config, "preflight") != {"ready": True}:
        raise RuntimeError("hermes_preflight_failed")


def _credentials(config):
    global _last_refresh
    asked = time.monotonic()
    with _REFRESH_LOCK:
        if _last_refresh and _last_refresh[0] > asked and _last_refresh[1] == config:
            return _last_refresh[2]
        auth = _auth_process(config, "refresh")
        if auth.get("provider") != "xai-oauth" or not isinstance(auth.get("api_key"), str) or not auth["api_key"]:
            raise RuntimeError("account_or_provider_mismatch")
        _last_refresh = (time.monotonic(), config, auth)
        return auth


async def normal_oauth_cloud(log=None, *, instructions=None, tools=(), header_vars=()):
    """Open a real OAuth-only session after an accepted device trigger."""
    config = _configuration(header_vars)
    from aiohttp import WSServerHandshakeError
    from talk_grok_realtime import _GrokWireSession, build_session_update
    from talk_realtime import SessionSetup
    log = log or (lambda *args, **kwargs: None)
    log("oauth_start")
    auth = await asyncio.to_thread(_credentials, config)
    log("oauth_ready")
    wire = _GrokWireSession(auth_token=auth["api_key"], auth_source="xai-oauth")
    setup = build_session_update(SessionSetup(
        model="grok-voice-latest", voice="ara", instructions=instructions or "",
        automatic_response=True,
    ))
    session = setup["session"]
    if instructions is None:
        session.pop("instructions", None)
    session["tools"] = list(tools)
    session["audio"]["input"].pop("transcription", None)
    session["audio"]["input"]["turn_detection"]["interrupt_response"] = False
    try:
        async with asyncio.timeout(CONNECT_TIMEOUT):
            await wire.connect(model="grok-voice-latest", session_update=setup)
        async with asyncio.timeout(SETUP_TIMEOUT):
            async for event in wire:
                if event.get("type") == "error":
                    raise RuntimeError("session_rejected")
                if event.get("type") == "session.updated":
                    receipt = event.get("session", {})
                    if not isinstance(receipt, dict):
                        raise RuntimeError("session_rejected")
                    audio = receipt.get("audio", {})
                    if not isinstance(audio, dict):
                        raise RuntimeError("format_rejected")
                    for direction in ("input", "output"):
                        nested = audio.get(direction, {})
                        if not isinstance(nested, dict):
                            raise RuntimeError("format_rejected")
                        formats = []
                        if "format" in nested:
                            formats.append(nested["format"])
                        if f"{direction}_audio_format" in receipt:
                            formats.append(receipt[f"{direction}_audio_format"])
                        if any(value != {"type": "audio/pcm", "rate": 24000} for value in formats):
                            raise RuntimeError("format_rejected")
                    log("session_ready")
                    return wire
            raise RuntimeError("setup_disconnected")
    except BaseException as exc:
        with contextlib.suppress(Exception):
            await wire.close()
        if isinstance(exc, asyncio.CancelledError):
            raise
        if type(exc) is RuntimeError and exc.args in (("session_rejected",), ("format_rejected",), ("setup_disconnected",)):
            raise
        if isinstance(exc, WSServerHandshakeError) and type(exc.status) is int and 100 <= exc.status < 600:
            raise RuntimeError(f"grok_handshake_{exc.status}") from None
        raise RuntimeError("grok_session_setup_failed") from None
