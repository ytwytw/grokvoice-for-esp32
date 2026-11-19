# Grok provider setup and evidence

The gateway uses the real `wss://api.x.ai/v1/realtime?model=grok-voice-latest`
wire from pinned Hermes Talk, authenticated only with an access token resolved
by a separate, unmodified Hermes Agent installation. There is no API-key,
cookie, shared-account, alternate-provider or paid-credit fallback. A device
trigger opens the cloud session; startup `--check` only validates local
configuration, source revision and imports. It does not validate login or
entitlement.

## Account and service prerequisites

Use your own account, your own upstream sign-in, and an account/service plan
that explicitly permits your intended realtime use. Whether a particular
consumer subscription authorizes or includes this endpoint is unresolved by
this project. Upstream's labels such as “SuperGrok / Premium+” are not evidence
that all subscriptions have access, or permission to reuse an upstream OAuth
client in another application. Resolve account-specific authorization and
entitlement with the provider before enabling live operation.

The official [speech API documentation](https://docs.x.ai/developers/model-capabilities/audio/voice)
documents the realtime endpoint with API authentication. It does not establish
consumer-subscription authorization for this OAuth integration. Review the
[consumer terms](https://x.ai/legal/terms-of-service),
[API/enterprise terms](https://x.ai/legal/terms-of-service-enterprise) and
[acceptable-use policy](https://x.ai/legal/acceptable-use-policy) with the
provider for the proposed use; this project makes no legal or entitlement
determination from those pages.

`GROK_ACCOUNT_AUTHORIZED=true` records the operator's affirmative decision; it
does not establish provider permission. `GROK_EXPECTED_EMAIL` pins the locally
stored ID-token email before and after every credential resolution. Decoding
this claim is an accidental-account-use check, not independent JWT signature validation.
Missing or different identities fail closed. No email, token, transcript or
upstream auth diagnostics are logged by this adapter.

## Supported upstream auth installation

Hermes Agent revision `9ffa7dff23726d8daa8b3e167b20a5fabc2e04ef` runs on
Python 3.14. Its broader package Python range exists for updater compatibility;
its `setup.py` deliberately rejects normal wheel/sdist installation. Do not
set `HERMES_NIX_BUILD` to bypass that guard. The gateway uses Python 3.12 for
its existing audio implementation, so Hermes runs in a separate process.

Hermes's own prerequisites are **git-lfs**, **Node.js 26 or newer with pnpm**,
and the Python 3.14 that its activation script provisions. Install git-lfs and
Node/pnpm first.

Prepare a separate full checkout with the upstream-supported developer
activation workflow, then sign in interactively yourself. This downloads and
prepares Hermes's own PM-managed dependencies; it is separate from installing
this gateway's requirements. Consult the pinned upstream
[installation guide](https://github.com/NousResearch/hermes-agent/blob/9ffa7dff23726d8daa8b3e167b20a5fabc2e04ef/website/docs/getting-started/installation.md)
and [development workflow](https://github.com/NousResearch/hermes-agent/blob/9ffa7dff23726d8daa8b3e167b20a5fabc2e04ef/CONTRIBUTING.md#development-setup).

```sh
git clone https://github.com/NousResearch/hermes-agent.git /path/to/hermes-agent
cd /path/to/hermes-agent
git checkout --detach 9ffa7dff23726d8daa8b3e167b20a5fabc2e04ef
umask 077
export HERMES_HOME=/path/to/private-hermes-data
source ./activate
hermes model
# Choose xAI Grok OAuth and complete the upstream browser/device-code sign-in.
export HERMES_SOURCE="$PWD"
export HERMES_PYTHON="$(python -c 'import sys; print(sys.executable)')"
```

The sign-in route above was checked in pinned source, rather than executed:
[`cmd_model` and `_PROVIDER_MODEL_FLOWS`](https://github.com/NousResearch/hermes-agent/blob/9ffa7dff23726d8daa8b3e167b20a5fabc2e04ef/hermes_cli/main.py#L1766)
dispatch `xai-oauth` to
[`_model_flow_xai_oauth`](https://github.com/NousResearch/hermes-agent/blob/9ffa7dff23726d8daa8b3e167b20a5fabc2e04ef/hermes_cli/model_setup_flows.py#L400),
which uses the upstream
[`_login_xai_oauth`](https://github.com/NousResearch/hermes-agent/blob/9ffa7dff23726d8daa8b3e167b20a5fabc2e04ef/hermes_cli/auth_xai.py#L467)
device-code flow and supported auth store. Activation, interactive sign-in and
the subsequent live account checks have not been run for this extraction.

Keep the Hermes checkout unmodified. The gateway checks its exact Git HEAD,
tracked modifications and actual auth-module imports. `HERMES_PYTHON` must be
the prepared Hermes interpreter with its dependencies, not the gateway venv.
Keep `HERMES_HOME` the same absolute data-directory path used during sign-in,
owned and writable only by the service user. Store these non-secret path
settings in your local gateway environment; do not copy auth JSON into this
repository or an image. Upstream controls its auth-store layout, profile/root
lookup and file locking. Use a dedicated Hermes home and avoid signing into or
switching that home while the gateway is running.

Required gateway environment:

```dotenv
TALK_PREFER_XAI_OAUTH=true
GROK_ACCOUNT_AUTHORIZED=true
GROK_EXPECTED_EMAIL=owner@example.invalid
HERMES_SOURCE=/path/to/hermes-agent
HERMES_PYTHON=/path/to/prepared-hermes-python3.14
HERMES_HOME=/path/to/private-hermes-data
```

Unset `XAI_API_KEY` and `TALK_XAI_API_KEY`. A configured key is rejected even
when OAuth credentials exist. `hermes model` must leave `xai-oauth` as the active
provider. Run the gateway's `--check` after configuration. A failed child
import reports `hermes_auth_import_failed`: run Hermes's own supported
environment checks interactively to repair its installation. The gateway
does not install or repair Hermes during a call.

## Runtime contract

`gateway.provider.normal_oauth_cloud(log=None, *, instructions=None, tools=())`
returns the real pinned `_GrokWireSession`, supporting async event iteration,
`send_json(sequence_of_events)` and `close()`. The factory uses a private pipe
to the configured Hermes Python; it invokes upstream
`resolve_xai_oauth_runtime_credentials()` with its default refresh-if-expiring
policy and active-provider/account checks before and after resolution. Valid
tokens are reused until upstream's expiry skew requires a refresh. No OAuth
client implementation, client secret or token store is copied. Credential
resolution is serialized per gateway process, overlapping requests reuse that
result, and upstream retains its auth-store locks. Use one gateway process per
auth home. The expected email travels in the child's environment, not its
arguments; the device's `ESPHOME_NOISE_PSK` is removed from that environment.

The websocket connection has a 35-second bound; setup acknowledgement has a
separate 20-second bound. `session.updated` is a setup receipt: xAI's normalized
echo may omit the audio block, as recorded in the pinned upstream fixture.
When present, nested `audio.input.format` / `audio.output.format` and flat
`input_audio_format` / `output_audio_format` must match
`{"type":"audio/pcm","rate":24000}`. Contradictory formats, malformed receipts,
missing acknowledgement, server errors, disconnection and timeout close the
wire and fail the call.
Server VAD creates responses automatically, with `interrupt_response=false`.
Transcription is not requested. Instructions are omitted when unspecified.
This project pins the upstream private wire API and tests that contract rather
than silently tracking a moving package version.

Runtime logs contain fixed reason codes or exception class names, never raw
Hermes/aiohttp error messages. Auth checks preserve `provider_mismatch`,
`account_mismatch`, `account_identity_unavailable`,
`hermes_python_314_required`, `hermes_auth_import_failed`, and allowlisted
upstream codes such as `xai_auth_missing`, `xai_refresh_failed` and
`xai_oauth_tier_denied`; unknown child diagnostics become `hermes_auth_failed`
or `hermes_refresh_failed`. Setup preserves `session_rejected`,
`format_rejected` and `setup_disconnected`. WebSocket upgrade failures report
`grok_handshake_<status>` (for example, `grok_handshake_401` or
`grok_handshake_403`); other setup failures report `grok_session_setup_failed`.
See [gateway troubleshooting](gateway.md#troubleshooting) for operator actions.

## Public inputs, notices and offline checks

| Input | Revision / SHA-256 |
| --- | --- |
| Hermes Talk (MIT), full pip package | `3b8f88bc9b39e7916523964debdce504af4d4990` |
| Talk source archive downloaded from GitHub | `ea72e33617b0e95fcbdab22888c2dbe9dc1bc89cddffc448cf7dd86d8afd0f95` |
| `talk_grok_realtime.py` | `f67f44156ed90547c70de9cef7374963d8f27f12ce2ce1d37a413a5412186d5b` |
| `talk_realtime.py` | `4d329bdbbeaf3d1be333e98def3c9b0b7ebd46bf50282c2a80f361bae4bfc2f7` |
| Hermes Agent (MIT), external full source | `9ffa7dff23726d8daa8b3e167b20a5fabc2e04ef` |
| Hermes source archive downloaded from GitHub | `2c581be60bef0c0c464178793336c13e80c1eb71466ce76119b4f85d8e422d33` |
| `hermes_cli/auth_xai.py` | `2a10b6d5f6e12644545579c56ab356fd15abf75138934c412c0f5f978f087ffb` |

Public archives came from GitHub codeload at those exact revisions; no deployed
image, private SDK copy, account data or credentials were used as dependencies.
See [Hermes Talk MIT](../licenses/hermes-talk-MIT.txt), its complete
[third-party notices](../licenses/hermes-talk-THIRD_PARTY_NOTICES.md), and
[Hermes Agent MIT](../licenses/hermes-agent-MIT.txt). The auth shim under
`gateway/vendor/` is project-authored glue, not a vendored OAuth client.

The provider tests run offline with fake auth and sockets, including the real
upstream wire over fake aiohttp. They cover account/provider changes, concurrent
resolution, default expiry-based refresh, key rejection, normalized/flat/nested
format receipts, HTTP handshake status, timeouts, cleanup, private child
environment and diagnostic suppression. These checks do not verify a complete
upstream PM installation, interactive sign-in, live service access or hardware. The operator must finish
the supported Hermes installation and resolve account-specific permission and
entitlement before live use.
