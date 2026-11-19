# Give Grok tools

The gateway starts with no tools enabled. You can turn on web search, search
public posts on X, or let Grok call tools on a remote Model Context Protocol
(MCP) server. Changes take effect when you restart the gateway.

## Turn on search

From the repository root, copy the [search example](../tools.example.json)
to your local configuration file:

```sh
cp -n tools.example.json tools.json
```

Keep both entries for web and X search. For web search alone, use this as the
entire contents of `tools.json`:

```json
[
  {"type": "web_search"}
]
```

Add this line to the gateway's local `.env`:

```sh
GROK_TOOLS_FILE=./tools.json
```

In the gateway terminal, stop the running process with Ctrl-C, then reload your
settings and start it again. Use the same speaker and gateway addresses you
used in the [gateway setup](gateway.md).

```sh
set -a
. ./.env
set +a
grokvoice --host grokvoice-pe.local --base-url http://gateway.local:8765 --check
grokvoice --host grokvoice-pe.local --base-url http://gateway.local:8765
```

Say “Okay Nabu,” wait for the tone, then ask “Search the web for the latest
ESPHome release.” With X search enabled, try “Search X for recent ESPHome
release announcements.”

## Add a custom MCP server

Use an HTTPS MCP endpoint that xAI can reach over the internet. It must support
Streamable HTTP or SSE. A command you run locally or an address reachable only
from your LAN will not work. Grok receives the configured headers and uses them
when calling the server. Choose a server you trust with the questions you send
it and a credential scoped to the tools you want to use.

For example, to keep web search and add a documentation lookup tool, replace
`tools.json` with the following. Substitute your endpoint and the exact tool
name advertised by your server:

```json
[
  {"type": "web_search"},
  {
    "type": "mcp",
    "server_url": "https://mcp.example.com/mcp",
    "server_label": "manuals",
    "allowed_tools": ["search_manual"],
    "headers_env": {"Authorization": "MANUALS_AUTH"}
  }
]
```

Give each server a distinct label. Omit `allowed_tools` to expose every tool on
that server. To disable the server, remove its entry. For a public endpoint
that needs no headers, omit `headers_env`.

For the authenticated example, add the following line to your private `.env`.
Replace the placeholder with your server's credential. The variable holds the
whole header value, including the space after `Bearer`.

```sh
MANUALS_AUTH='Bearer REPLACE_WITH_YOUR_MCP_TOKEN'
```

Keep credentials out of the URL and JSON. Run the check and
restart commands above, then ask “Use the manuals tool to look up how to
change the volume.”

The offline check catches malformed configuration and missing header values.
If the check passes but a lookup fails, confirm the endpoint is reachable
from the internet and the server recognizes the credential and tool name.
For the provider's tool fields, see the [xAI voice guide](https://docs.x.ai/developers/model-capabilities/audio/speech-to-speech).
