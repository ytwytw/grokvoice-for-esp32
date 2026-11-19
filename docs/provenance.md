# Provenance and release limits

## Project source

The gateway implements a one-device Voice PE conversation bridge.
It retains encrypted ESPHome capture and controls, bounded audio queues,
streamed WAV replies, mute and disconnect cleanup, server voice activity
handling and playback-gated follow-up. Wake detection is the official
on-device Okay Nabu model; the gateway adds no custom wake word, recordings,
reminders, announcements, remote firmware updates or external tools.
Feedback tones are generated locally using the Python standard library.

The gateway and firmware have not yet been accepted on physical hardware.
Offline acceptance uses synthetic audio and fake device/provider messages;
provider access and hardware acceptance are separate.

## External dependencies

- [ESPHome](https://github.com/esphome/esphome/releases/tag/2026.10.2), 2026.10.2,
  supplies the build command. Firmware hardware configuration and Voice Kit are
  pinned separately. Exact source, wake-model hashes and notices are recorded in
  [firmware provenance](../firmware/PROVENANCE.md) and
  [upstream license](../firmware/upstream-LICENSE.txt).
- [aioesphomeapi](https://github.com/esphome/aioesphomeapi), 46.12.0 (MIT), supplies
  the encrypted ESPHome client and voice/media messages. Its dependencies are
  resolved by pip from the pinned direct requirement. This is not a full lock
  with hashes or a promise of bit-for-bit reproducibility.
- The gateway targets Python 3.12. Audio conversion uses its standard-library
  `audioop.ratecv`; Python 3.13+ removed that module and is not supported here.
- Grok wire and authentication dependencies, their pinned commits, installation
  boundaries and notices are documented in the [provider guide](provider.md).
  The gateway does not ship an OAuth credential or implement its own login client.

## Decisions and limits

One Voice PE is supported. The official pinned Okay Nabu model runs on the
speaker only. No custom wake data or model is shipped or loaded by the gateway.
Continuous idle audio crosses the encrypted LAN link but is discarded there.
Cloud upload is gated by call state; reply HTTP is plaintext on the trusted LAN.
The eight-second follow-up starts after actual playback, not after generation.
Speech during playback is discarded; a button press or mute ends the call.
The knob changes local playback volume. There are no search tools or cloud
volume/reminder commands in v1.

## Before redistribution or public release

The project's own code is licensed under [Apache-2.0](../LICENSE). Retained
third-party materials keep their original notices, summarized in [NOTICE](../NOTICE).
The upstream ESPHome recipe and runtime retain their own licensing terms.
Do not publish compiled firmware, generated credentials, account state or audio.
Review upstream model terms separately before redistributing model bytes or
compiled firmware.

Each operator must confirm provider authorization and account entitlement for
their own use. Open-source code licenses do not
grant access to a hosted service. A consumer subscription does not by itself
establish permission for automated OAuth voice access. This project makes no
claim of official affiliation, general subscription eligibility, unlimited use,
or provider-side no-retention.
