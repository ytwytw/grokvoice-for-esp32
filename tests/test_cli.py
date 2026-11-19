# SPDX-License-Identifier: Apache-2.0
import base64
import contextlib
import io
import os
import unittest
from unittest.mock import patch
from gateway.__main__ import main, parser, validate


class CLITests(unittest.TestCase):
    def args(self, *extra):
        return parser().parse_args(['--host', 'voice-device.local', '--base-url',
                                   'http://gateway.local:8765', *extra])

    def test_missing_encryption_fails_before_provider(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, '32-byte'):
                validate(self.args())

    def test_public_example_key_rejected(self):
        key = base64.b64encode(bytes(range(32))).decode()  # Former public example.
        with patch.dict(os.environ, {'ESPHOME_NOISE_PSK': key}, clear=True):
            with self.assertRaisesRegex(ValueError, 'public example'):
                validate(self.args())

    def test_bad_origins_and_ports(self):
        for url in ('https://gateway.local:8765', 'http://user@host:8765',
                    'http://host:8765/path', 'http://host:1234', 'http://host:8765?x=y'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate(self.args('--base-url', url))

    def test_startup_hides_external_error_text(self):
        output = io.StringIO()
        with patch('gateway.__main__.validate', side_effect=RuntimeError('sensitive detail')):
            with contextlib.redirect_stderr(output):
                self.assertEqual(main(['--host', 'device', '--base-url', 'http://host:8765']), 1)
        self.assertEqual(output.getvalue().strip(), 'grokvoice: RuntimeError')

    def test_help_does_not_import_provider_or_network(self):
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as result:
            main(['--help'])
        self.assertEqual(result.exception.code, 0)

    def test_error_exit_without_secret_output(self):
        output = io.StringIO()
        with patch.dict(os.environ, {'ESPHOME_NOISE_PSK': 'private-bad-key'}, clear=True):
            with contextlib.redirect_stderr(output):
                self.assertEqual(main(['--host', 'device', '--base-url', 'http://host:8765']), 1)
        self.assertNotIn('private-bad-key', output.getvalue())
