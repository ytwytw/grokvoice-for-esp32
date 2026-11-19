# Contributor and agent guide

A one-speaker Python gateway joins an ESPHome Voice PE to authorized Grok
realtime access. Read README.md and the linked guides before changing behavior.

## Layout

- `gateway/`: CLI, device bridge, audio conversion, reply HTTP and provider adapter.
- `gateway/vendor/hermes_auth.py`: subprocess shim for separate Hermes sign-in.
- `firmware/`: Voice PE YAML and local feedback-tone generator.
- `tests/`: offline fake-device/provider tests.
- `docs/`: setup, controls, provider requirements, provenance.
- `licenses/`: retained upstream notices; do not replace them with Apache headers.

## Commands (repository root)

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install --no-deps -e .
python -m pip check
python -m unittest discover -s tests -v
grokvoice --help
```

Firmware validation uses its own environment:

```sh
python3.12 -m venv .venv-firmware
. .venv-firmware/bin/activate
python -m pip install -r requirements-firmware.txt
python firmware/generate-tones.py
esphome config firmware/voice-pe.yaml
```

First create ignored `firmware/secrets.yaml` from the example with your local
values as described in docs/build-and-run.md. Configuration validation fetches
public build inputs; it does not compile or contact a device. Never show secrets.

Default ports: encrypted ESPHome API 6053; gateway reply HTTP 8765. Start and
configuration commands are in docs/gateway.md; do not start live services for an
offline change. Provider sign-in uses a separate Python 3.14 Hermes installation.

Keep patches small, preserve mute/disconnect cleanup and bounded audio queues,
and run the relevant checks. Tests must not contact devices, read real account
state or call a provider. Ask for explicit permission before build/flash,
account access or deployment. Never add credentials, local paths, recordings or
private network details. Follow SECURITY.md and preserve third-party notices.
