# SPDX-License-Identifier: Apache-2.0
"""Load the server-side tools offered in each voice session."""
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit


def load_tools(path):
    if not path:
        return [], ()
    try:
        entries = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError("GROK_TOOLS_FILE must point to a readable JSON file") from None
    if not isinstance(entries, list):
        raise ValueError("tools file must contain a JSON array")

    tools = []
    header_vars = set()
    labels = set()
    for index, entry in enumerate(entries, 1):
        if entry in ({"type": "web_search"}, {"type": "x_search"}):
            tools.append(entry)
            continue
        prefix = f"tools file entry {index}"
        if not isinstance(entry, dict) or entry.get("type") != "mcp":
            raise ValueError(f"{prefix}: use web_search, x_search or mcp")
        if entry.keys() - {"type", "server_url", "server_label", "allowed_tools", "headers_env"}:
            raise ValueError(f"{prefix}: unknown MCP field (use headers_env for headers)")
        url = entry.get("server_url")
        try:
            parts = urlsplit(url if isinstance(url, str) else "")
            valid_url = (parts.scheme == "https" and parts.hostname and parts.username is None
                         and parts.port != 0 and not parts.fragment and not re.search(r"[\s\\\x00-\x1f\x7f]", url))
        except ValueError:
            valid_url = False
        if not valid_url:
            raise ValueError(f"{prefix}: server_url must be an HTTPS endpoint without user info or fragment")
        label = entry.get("server_label")
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"{prefix}: server_label must be a nonempty string")
        if label in labels:
            raise ValueError(f"{prefix}: each MCP server needs a unique label")
        labels.add(label)
        tool = {"type": "mcp", "server_url": url, "server_label": label}
        if "allowed_tools" in entry:
            names = entry["allowed_tools"]
            if not isinstance(names, list) or not names or not all(isinstance(n, str) and n.strip() for n in names):
                raise ValueError(f"{prefix}: allowed_tools must be a nonempty list of tool names")
            tool["allowed_tools"] = names
        if "headers_env" in entry:
            refs = entry["headers_env"]
            if not isinstance(refs, dict):
                raise ValueError(f"{prefix}: headers_env must map header names to environment variable names")
            headers = {}
            for name, ref in refs.items():
                if (not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name)
                        or not isinstance(ref, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", ref)):
                    raise ValueError(f"{prefix}: invalid header or environment variable name")
                value = os.environ.get(ref)
                if not value or re.search(r"[\x00-\x1f\x7f]", value):
                    raise ValueError(f"{prefix}: set each referenced header variable to a nonempty single-line value")
                header_vars.add(ref)
                headers[name] = value
            tool["headers"] = headers
        tools.append(tool)
    return tools, tuple(sorted(header_vars))
