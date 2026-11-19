# Source and dependency licenses

## Project source

The Python gateway and feedback-tone generator are project code. The firmware
YAML adapts the upstream Voice PE recipe. For setup and controls, see the
[user guide](user-guide.md).

## External dependencies

- [ESPHome](https://github.com/esphome/esphome/releases/tag/2026.10.2), 2026.10.2,
  supplies the build command. Firmware hardware configuration and Voice Kit are
  pinned separately. Exact source, wake-model hashes and notices are recorded in
  [firmware provenance](../firmware/PROVENANCE.md) and
  [upstream license](../firmware/upstream-LICENSE.txt).
- [aioesphomeapi](https://github.com/esphome/aioesphomeapi), 46.12.0 (MIT), supplies
  the encrypted ESPHome client and voice/media messages. Its dependencies are
  resolved by pip from the pinned direct requirement.
- The gateway targets Python 3.12. Audio conversion uses its standard-library
  `audioop.ratecv`; Python 3.13+ removed that module and is not supported here.
- Grok wire and authentication dependencies, their pinned commits, installation
  boundaries and notices are documented in the [provider guide](provider.md).
  The gateway does not ship an OAuth credential or implement its own login client.

## Redistribution

The project's own code is licensed under [Apache-2.0](../LICENSE). Retained
third-party materials keep their original notices, summarized in [NOTICE](../NOTICE).
The upstream ESPHome recipe and runtime retain their own licensing terms.
Do not publish compiled firmware, generated credentials, account state or audio.
Review upstream model terms separately before redistributing model bytes or
compiled firmware.

This is an independent community project. Use an account and service plan that permit your intended Grok realtime use.
Provider access and data retention follow the provider's terms and account settings;
see the [provider guide](provider.md).
