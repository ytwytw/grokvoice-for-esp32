# SPDX-License-Identifier: Apache-2.0
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gateway.tools import load_tools


class ToolsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "tools.json"
        self.server = {"type": "mcp", "server_label": "manuals", "server_url": "https://mcp.example.com/mcp"}

    def load(self, entries):
        self.path.write_text(json.dumps(entries))
        return load_tools(self.path)

    def test_defaults_search_and_public_server(self):
        self.assertEqual(load_tools(None), ([], ()))
        entries = [{"type": "web_search"}, {"type": "x_search"}, self.server]
        self.assertEqual(self.load(entries), (entries, ()))

    def test_resolves_header_values(self):
        entry = dict(self.server, allowed_tools=["search_manual"], headers_env={"Authorization": "MANUALS_AUTH"})
        with patch.dict(os.environ, {"MANUALS_AUTH": "sample header"}):
            self.assertEqual(self.load([entry]), ([dict(self.server, allowed_tools=["search_manual"],
                                                      headers={"Authorization": "sample header"})], ("MANUALS_AUTH",)))

    def test_mcp_labels_are_unique(self):
        with self.assertRaisesRegex(ValueError, "label"):
            self.load([self.server, dict(self.server, server_url="https://other.example.com/mcp")])

    def test_invalid_and_missing_files(self):
        with self.assertRaises(ValueError):
            load_tools(self.path)
        self.path.write_text("[")
        with self.assertRaises(ValueError):
            load_tools(self.path)

    def test_rejects_malformed_entries_and_literal_headers(self):
        for entries in ({}, [42], [{"type": "function"}], [{"type": "web_search", "extra": True}],
                        [dict(self.server, server_label="")], [dict(self.server, allowed_tools=[])],
                        [dict(self.server, server_url="http://mcp.example.com")],
                        [dict(self.server, server_url="https://user@mcp.example.com")],
                        [dict(self.server, headers={"Authorization": "private-example"})],
                        [dict(self.server, headers_env={"Authorization": "Bearer private-example"})]):
            with self.subTest(entries=entries), self.assertRaises(ValueError) as error:
                self.load(entries)
            self.assertNotIn("private-example", str(error.exception))

    def test_missing_and_multiline_header_values(self):
        for env in ({}, {"MANUALS_AUTH": "invalid\nheader"}):
            with patch.dict(os.environ, env, clear=True), self.assertRaisesRegex(ValueError, "header variable"):
                self.load([dict(self.server, headers_env={"Authorization": "MANUALS_AUTH"})])
