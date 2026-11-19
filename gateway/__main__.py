# SPDX-License-Identifier: Apache-2.0
"""Connect one Voice PE to Grok using your authorized account."""
import argparse
import asyncio
import base64
import binascii
import logging
import os
import signal
import sys
from urllib.parse import urlsplit


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('--host', required=True, help='Voice PE hostname or IP address')
    result.add_argument('--base-url', required=True,
                        help='HTTP URL of this gateway reachable by the speaker, including port')
    result.add_argument('--bind', default='0.0.0.0', help='reply HTTP bind address (default: %(default)s)')
    result.add_argument('--http-port', type=int, default=8765)
    result.add_argument('--check', action='store_true',
                        help='check settings, pinned Hermes checkout and both Python environments offline')
    return result


def validate(args):
    if not args.host.strip() or any(c.isspace() for c in args.host) or '/' in args.host:
        raise ValueError('host must be one hostname or IP address')
    if not 1 <= args.http_port <= 65535:
        raise ValueError('http-port must be in 1..65535')
    try:
        url = urlsplit(args.base_url)
        port = url.port
    except ValueError:
        raise ValueError('base-url must contain a valid host and port') from None
    if (url.scheme != 'http' or not url.hostname or url.username or url.password
            or url.path not in ('', '/') or url.query or url.fragment):
        raise ValueError('base-url must be an HTTP origin, for example http://gateway.local:8765')
    if (80 if port is None else port) != args.http_port:
        raise ValueError('base-url port must match http-port')
    try:
        key = base64.b64decode(os.environ.get('ESPHOME_NOISE_PSK', ''), validate=True)
    except (ValueError, binascii.Error):
        raise ValueError('ESPHOME_NOISE_PSK must encode a 32-byte encryption key') from None
    if len(key) != 32:
        raise ValueError('ESPHOME_NOISE_PSK must encode a 32-byte encryption key')
    if key == bytes(range(32)):
        raise ValueError('replace the public example encryption key on the device and gateway')
    from .provider import validate_environment
    validate_environment()
    from aioesphomeapi import APIClient  # noqa: F401
    from .bridge import Bridge, Replies, connect_forever, serve  # noqa: F401


async def run(args):
    from aioesphomeapi import APIClient
    from .bridge import Bridge, Replies, connect_forever, serve
    from .provider import normal_oauth_cloud
    replies = Replies(args.base_url.rstrip('/'))
    server = serve(replies, args.bind, args.http_port)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        await connect_forever(
            lambda: APIClient(args.host, 6053, password=None,
                              noise_psk=os.environ['ESPHOME_NOISE_PSK'], client_info='grokvoice'),
            lambda device: Bridge(device, replies, normal_oauth_cloud), stop)
    finally:
        replies.clear()
        await asyncio.to_thread(server.shutdown)
        server.server_close()


def main(argv=None):
    cli = parser()
    args = cli.parse_args(argv)
    try:
        validate(args)
        if args.check:
            print('Configuration and imports OK; no device, account, or provider connection attempted.')
        else:
            logging.basicConfig(format='%(name)s %(levelname)s %(message)s')
            logging.getLogger('gateway').setLevel(logging.INFO)
            asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130
    except ValueError as exc:
        print(f'grokvoice: {exc}', file=sys.stderr)
        return 1
    except (RuntimeError, ImportError) as exc:
        from .provider import safe_reason
        print(f'grokvoice: {safe_reason(exc)}', file=sys.stderr)
        return 1
    except Exception:
        print('grokvoice: startup failed; check bind address, port and installation.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
