# Set up Grok access

Use your own Grok account with permission for realtime voice through OAuth.
Hermes handles sign-in. The gateway opens a session when you start a conversation.

## Account and service prerequisites

Check that your service plan permits this use before setting up the gateway.
The official [speech API documentation](https://docs.x.ai/developers/model-capabilities/audio/voice)
describes the realtime endpoint. Review the
[consumer terms](https://x.ai/legal/terms-of-service),
[API/enterprise terms](https://x.ai/legal/terms-of-service-enterprise) and
[acceptable-use policy](https://x.ai/legal/acceptable-use-policy) with the
provider for your intended use.

## Sign in with Hermes

Use Bash and Git with Git LFS. Hermes needs Node.js 26 or newer. Its
activation script provides the pinned Python 3.14 interpreter and pnpm.
The gateway runs in its own Python 3.12 environment.

Choose locations for the checkout and private account data. Run these
commands in a new terminal. When `hermes model` prompts you, select xAI Grok
OAuth and complete the browser sign-in. See the pinned upstream
[developer setup](https://github.com/NousResearch/hermes-agent/blob/9ffa7dff23726d8daa8b3e167b20a5fabc2e04ef/CONTRIBUTING.md#development-setup).

```sh
git clone https://github.com/NousResearch/hermes-agent.git "$HOME/hermes-agent"
cd "$HOME/hermes-agent"
git checkout --detach 9ffa7dff23726d8daa8b3e167b20a5fabc2e04ef
umask 077
export HERMES_HOME="$HOME/.hermes-grokvoice"
source ./activate
hermes model
# Choose xAI Grok OAuth and complete the upstream browser/device-code sign-in.
export HERMES_SOURCE="$PWD"
export HERMES_PYTHON="$(python -c 'import sys; print(sys.executable)')"
printf '%s\n' "$HERMES_SOURCE" "$HERMES_PYTHON" "$HERMES_HOME"
```

## Configure the gateway account

Copy the three paths printed above into the matching `HERMES_SOURCE`,
`HERMES_PYTHON` and `HERMES_HOME` fields in the gateway's private `.env`.
Keep the checkout at the specified revision with its tracked files unchanged.
Use one gateway per Hermes home and keep the directory private to that user.

Set `GROK_EXPECTED_EMAIL` to the email you signed in with. Keep
`TALK_PREFER_XAI_OAUTH=true` and set `GROK_ACCOUNT_AUTHORIZED=true` once
you have confirmed your access. Unset `XAI_API_KEY` and `TALK_XAI_API_KEY`.
The gateway checks the active provider and account when it obtains a token.

Return to the [gateway setup](gateway.md) in a new terminal.

## During a call

Grok detects speech and creates replies automatically. Speech during playback
is ignored; press the center button or use mute to end the call. You can
optionally [add web search, X search or a remote MCP server](tools.md).

If setup or playback fails, the call ends. Gateway logs use fixed reason codes
or exception class names. See [gateway troubleshooting](gateway.md#troubleshooting)
for the next step, and keep auth files and raw provider messages out of reports.

## Dependencies and licenses

| Input | Revision / SHA-256 |
| --- | --- |
| Hermes Talk (MIT), full pip package | `3b8f88bc9b39e7916523964debdce504af4d4990` |
| Talk source archive downloaded from GitHub | `ea72e33617b0e95fcbdab22888c2dbe9dc1bc89cddffc448cf7dd86d8afd0f95` |
| `talk_grok_realtime.py` | `f67f44156ed90547c70de9cef7374963d8f27f12ce2ce1d37a413a5412186d5b` |
| `talk_realtime.py` | `4d329bdbbeaf3d1be333e98def3c9b0b7ebd46bf50282c2a80f361bae4bfc2f7` |
| Hermes Agent (MIT), external full source | `9ffa7dff23726d8daa8b3e167b20a5fabc2e04ef` |
| Hermes source archive downloaded from GitHub | `2c581be60bef0c0c464178793336c13e80c1eb71466ce76119b4f85d8e422d33` |
| `hermes_cli/auth_xai.py` | `2a10b6d5f6e12644545579c56ab356fd15abf75138934c412c0f5f978f087ffb` |

The public dependencies come from GitHub archives at the revisions above.
See [Hermes Talk MIT](../licenses/hermes-talk-MIT.txt), its complete
[third-party notices](../licenses/hermes-talk-THIRD_PARTY_NOTICES.md), and
[Hermes Agent MIT](../licenses/hermes-agent-MIT.txt). The auth shim under
`gateway/vendor/` is project-authored glue, not a vendored OAuth client.
