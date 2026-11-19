# SPDX-License-Identifier: Apache-2.0
"""Pipe-only adapter executed by the separately installed Hermes Python.

This file implements no OAuth protocol. All credential storage and refresh are
handled by the unmodified upstream Hermes auth modules.
"""
import base64
import contextlib
import json
import logging
import os
import sys

AUTH_ERROR_CODES = frozenset({
    "provider_mismatch", "account_mismatch", "account_identity_unavailable",
    "hermes_python_314_required", "hermes_auth_import_failed", "invalid_auth_operation",
    "hermes_auth_failed", "xai_auth_missing", "xai_auth_invalid_shape",
    "xai_auth_missing_access_token", "xai_auth_missing_refresh_token",
    "xai_oauth_tier_denied", "xai_refresh_failed", "xai_refresh_invalid_json",
    "xai_refresh_invalid_response", "xai_refresh_missing_access_token",
    "xai_discovery_invalid", "xai_discovery_failed", "xai_discovery_invalid_json",
    "xai_discovery_incomplete",
})


def error_code(exc):
    code = exc.args[0] if type(exc) is RuntimeError and len(exc.args) == 1 else getattr(exc, "code", None)
    return code if isinstance(code, str) and code in AUTH_ERROR_CODES else "hermes_auth_failed"


def _account(auth, xai, expected):
    if auth.get_active_provider() != "xai-oauth":
        raise RuntimeError("provider_mismatch")
    tokens = xai._read_xai_oauth_tokens()["tokens"]
    try:
        payload = tokens.get("id_token", "").split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        email = claims.get("email")
        if not isinstance(email, str) or not email:
            raise ValueError
    except (AttributeError, IndexError, TypeError, ValueError):
        raise RuntimeError("account_identity_unavailable") from None
    if email.casefold() != expected.casefold():
        raise RuntimeError("account_mismatch")


def run(mode, expected=""):
    if sys.version_info[:2] != (3, 14):
        raise RuntimeError("hermes_python_314_required")
    try:
        import hermes_cli.auth as auth
        import hermes_cli.auth_xai as xai
    except ImportError:
        raise RuntimeError("hermes_auth_import_failed") from None
    if not callable(xai.resolve_xai_oauth_runtime_credentials):
        raise RuntimeError("hermes_auth_import_failed")
    if mode == "preflight":
        return {"ready": True}
    if mode != "refresh":
        raise RuntimeError("invalid_auth_operation")
    _account(auth, xai, expected)
    result = xai.resolve_xai_oauth_runtime_credentials()
    _account(auth, xai, expected)
    if result.get("provider") != "xai-oauth" or not result.get("api_key"):
        raise RuntimeError("provider_mismatch")
    return {"provider": "xai-oauth", "api_key": result["api_key"]}


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    try:
        # Hermes diagnostics may contain auth responses; only the narrow result
        # below is allowed onto this private pipe, never into gateway logs.
        with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            result = run(sys.argv[1], os.environ.get("GROK_EXPECTED_EMAIL", ""))
        print(json.dumps(result))
    except BaseException as exc:
        print(json.dumps({"error": error_code(exc)}))
        sys.exit(1)
