# Install and run the gateway

Run these commands from the repository root in a new terminal. Install the gateway
with Python **3.12** and Git. For sign-in, prepare the [separate Hermes environment](provider.md)
on Python **3.14**. Installation downloads public dependencies.
Run the gateway on Linux.

## Install

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install --no-deps -e .
python -m pip check
grokvoice --help
python -m unittest discover -s tests -v
```

The tests use generated PCM, a fake device and fake provider messages. They do
not load account credentials or connect to a speaker or Grok. Build dependencies
for the firmware are separate; see the [build guide](build-and-run.md).

## Configure your own device and account

```sh
umask 077
cp -n .env.example .env
chmod 600 .env
```

Edit `.env` locally. Set `ESPHOME_NOISE_PSK` to the same base64 encryption key
used in your firmware's `api_encryption_key`. Use a separate private auth directory
for your own account; never copy another person's token store. Follow the
[upstream sign-in and entitlement instructions](provider.md) first. Only set the
authorization acknowledgment after confirming that your account and intended
use are allowed. The acknowledgment cannot grant service access.

The example is a shell file, not an automatic dotenv loader. Load it explicitly:

```sh
set -a
. ./.env
set +a
grokvoice --host grokvoice-pe.local --base-url http://gateway.local:8765 --check
```

Replace `gateway.local` with the LAN address of your gateway computer.
The default speaker name is `grokvoice-pe.local`. Use its LAN IP if your
computer cannot resolve that name. `--check` validates settings
and imports the gateway dependencies. It also runs Git to check the Hermes
revision and tracked files, then starts the configured Hermes Python interpreter
to check its version and auth imports. It runs locally without reading tokens.
After starting the gateway, follow the [conversation guide](user-guide.md).

To add web search, X search or a remote MCP server, follow the [tools guide](tools.md)
and set `GROK_TOOLS_FILE` before starting the gateway.

## Start

```sh
grokvoice --host grokvoice-pe.local --base-url http://gateway.local:8765
```

`python -m gateway` accepts the same arguments. Leave this command running;
Ctrl-C or SIGTERM closes the session and HTTP server. The gateway reconnects to
the speaker after a lost connection, with mute treated as unknown until its
state arrives again. A new cloud session opens only on an accepted trigger.

The speaker must reach the advertised `--base-url` over HTTP. The default reply
port is 8765; if you change `--http-port`, also change the port in `--base-url`.
Use `--bind` to select a local interface if needed. The ESPHome connection uses
port 6053 and encryption is required. Reply audio uses temporary random URL paths
on plaintext HTTP. Use a trusted LAN, keep these ports off the public internet,
and restrict access with your host firewall where appropriate. The service does
not provide TLS or user accounts for the reply server.

For a persistent service, run the exact same foreground command under your
host's service manager, with this checkout as its working directory and a
private environment containing the configured values. Run only one gateway per
speaker and one process per auth store: refresh tokens can rotate. There is no
service installation step that changes your machine automatically.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Command not found | Activate `.venv` and repeat the editable install. |
| Startup rejects a setting | Read the fixed error reason; check the key's base64 format, URL port and provider environment. Do not paste secrets into an issue. |
| Import or dependency failure | Use Python 3.12, rerun both install commands, then `python -m pip check`. |
| Device never becomes ready | Check LAN name resolution, port 6053, matching encryption keys, compatible firmware, and the mute switch. |
| Trigger works but Grok does not answer | Check upstream sign-in and account entitlement. A rejection is not a reason to switch to cookies, shared tokens or API keys. |
| No playback | Verify the speaker can resolve and reach the advertised gateway HTTP URL, port and host firewall. `localhost` refers to the speaker itself. |
| Speech during a reply is ignored | Wait for playback to finish. Speech interruption is intentionally disabled. |
| Follow-up is ignored | Start again after the eight-second window. A call also ends on a speech or response timeout. |
| Network or provider failure | The current call ends and audio URLs are revoked. Check connectivity, then start a new call. |

### Log messages

When the encrypted device link is ready, the gateway logs `device_connected`.
A failed call or device connection includes a reason. Use that reason to
decide what to check first.

| Reason | What to check |
| --- | --- |
| `own_account_authorization_required` | Shown by `--check` until you set `GROK_ACCOUNT_AUTHORIZED=true` in `.env`, which confirms you are authorized to use your own account this way; see the [provider guide](provider.md). |
| `normal_oauth_required`, `expected_email_required` | Use the normal Hermes xAI Grok OAuth sign-in and set `GROK_EXPECTED_EMAIL` to that account's email. |
| `hermes_source_absolute_path_required`, `hermes_python_absolute_path_required`, `hermes_home_absolute_path_required` | Set `HERMES_SOURCE`, `HERMES_PYTHON` and `HERMES_HOME` to absolute paths. |
| `provider_dependencies_unavailable_or_modified`, `hermes_preflight_failed` | The Hermes checkout is missing, modified or not activated. Re-check it out at the pinned revision and run `source ./activate` again. |
| `xai_oauth_tier_denied` | Your account or subscription tier is not allowed to use this access. Check entitlement with the provider. |
| `account_or_provider_mismatch` | The signed-in account or provider differs from the configured one. Sign in again with the expected account. |
| `setup_disconnected`, `grok_session_setup_failed` | The Grok session closed during setup. Retry; if it repeats, check connectivity, sign-in and entitlement. |
| `required_firmware_entities_missing` | The connected device must run this repository's Voice PE recipe. |
| `hermes_python_314_required`, `hermes_auth_import_failed` | Set `HERMES_PYTHON` to the interpreter from the activated Hermes checkout. |
| `hermes_revision_mismatch` | Check out the Hermes revision listed in the [provider guide](provider.md). |
| `provider_mismatch` | In the dedicated Hermes home, check that the active provider is xAI Grok OAuth. |
| `account_mismatch`, `account_identity_unavailable` | Check the email in `GROK_EXPECTED_EMAIL` and the account you signed into. A missing email claim also stops the call. |
| `xai_auth_missing`, `xai_refresh_failed` | Check that the gateway uses the same Hermes home as sign-in. If the session expired, sign in again with Hermes. |
| `grok_handshake_401`, `grok_handshake_403` | Grok rejected the connection. Check sign-in for 401 and provider permission or account entitlement for 403. |
| `format_rejected`, `session_rejected` | The service rejected setup or reported an incompatible audio format. If tools are enabled, remove the failing entry from the tools file and restart, or set the file to `[]` to retry without tools. Check the pinned provider versions if setup still fails. |
| `provider_disconnected`, `provider_error` | The provider closed the connection or returned an error during the call. Check connectivity and account status. |
| `response_failed`, `overlapping_response` | The reply was empty, incomplete or overlapped another reply. Start a new call. |
| `playback_failed` | Check the speaker can reach the gateway's advertised HTTP address. |
| A connection exception such as `TimeoutError` | Use the event name to locate the failure. Check the speaker's LAN connection for `device_connect_failed`, or the provider and reply path for `turn_failed`. |

Do not share raw provider payloads, auth files, microphone recordings, account
identifiers or environment dumps when reporting a problem.
