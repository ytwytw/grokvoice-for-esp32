# Firmware inputs and contract

`voice-pe.yaml` is the self-build entry point for Home Assistant Voice Preview Edition only. It pins project version `0.1.0`; use ESPHome `2026.10.2` from the repository's firmware requirements. Run `python3 firmware/generate-tones.py` from the repository root before ESPHome configuration or compilation. The script creates five original 16 kHz, mono, signed 16-bit PCM WAV feedback tones under `firmware/assets/`; it uses only the Python standard library. There are no copied speech recordings or private sound assets.

## Public upstream inputs

The hardware/audio YAML and feedback layout are adapted from [ESPHome Home Assistant Voice PE](https://github.com/esphome/home-assistant-voice-pe/tree/d4e6fa43d6a1a7d342b7d4d403567e06516719de), revision `d4e6fa43d6a1a7d342b7d4d403567e06516719de`. Changes replace the Home Assistant conversation path with the gateway controls below, replace upstream sounds with generated tones, and omit OTA, XMOS update payloads and unrelated integrations. Attribution and upstream license terms are retained in `upstream-LICENSE.txt`.

The Voice Kit component is fetched directly from that same pinned public revision, at `esphome/components/voice_kit`. It resets/configures the XMOS audio processor over GPIO4 and I2C; it is required even though XMOS updating is disabled. No component runtime source is copied into this repository. Upstream C/C++ runtime is GPLv3 and Python/YAML is MIT under the upstream license; a locally compiled firmware is not entirely governed by this repository's own license. The recipe assumes a functioning existing Voice PE XMOS image and does not install, update or repair it.

The only wake model is the official Voice PE selection, Kevin Ahrendt's [Okay Nabu `20241226.3`](https://github.com/kahrendt/microWakeWord/releases/tag/okay_nabu_20241226.3). ESPHome downloads it from the explicit release URL in `voice-pe.yaml`; no model bytes or custom wake training assets are shipped here. The release manifest names `okay_nabu.tflite` from that same release directory. Source hashes:

| Input | SHA-256 |
| --- | --- |
| [`okay_nabu.json`](https://github.com/kahrendt/microWakeWord/releases/download/okay_nabu_20241226.3/okay_nabu.json) | `f8026e2ce93a0855ca23483036fd2d74ee924a2588d9ea6a6c6c7478fbf4be57` |
| [`okay_nabu.tflite`](https://github.com/kahrendt/microWakeWord/releases/download/okay_nabu_20241226.3/okay_nabu.tflite) | `d89128c4d16a72de429119fb2254ce46649553c2a24f5dd840175c80d7b9d094` |

These hashes identify the public inputs; ESPHome's remote model loader does not enforce SHA-256 against this table. Upstream release availability is required during a fresh configuration/build. See the model project's own terms before redistributing model files or compiled firmware.

## Hardware retained

The recipe preserves the Voice PE's ESP32-S3, 16 MB flash, octal 80 MHz PSRAM, XMOS control/reset, stereo microphone input (GPIO13/14/15), stereo speaker output (GPIO7/8/10), AIC3204 codec over GPIO5/6, speaker amplifier GPIO47, jack detect GPIO17, button GPIO0, hardware mute GPIO3, dial GPIO16/18 and 12-pixel LED ring GPIO21 powered by GPIO45. Microphone channel 0 remains the conversation channel; channel 1 feeds local Okay Nabu with the upstream gain factor of 4. Mixer/resampler/output settings follow the upstream audio recipe. The generic ESP32 board identifier does not make the wiring portable.

## Gateway native API contract

The API uses a user-generated encryption key shared with the gateway. No Home Assistant server, web controls, OTA service or XMOS update automation is configured.

| Entity / action | Meaning |
| --- | --- |
| `Reply` media player | Gateway requests HTTP WAV playback as an announcement; its actual playback state determines completion. |
| `Talk Requested` | 100 ms pulse from short button press / Talk API button; gateway starts an idle conversation or stops an active one. |
| `New Context Requested` | 100 ms pulse from a one-second hold / New Context API button, subject to mute and connection checks. |
| `Stop Requested` | 100 ms pulse from Stop API button, mute or disconnect cleanup; local announcement playback stops immediately. |
| `Wake Requested` | 100 ms pulse only from local Okay Nabu detection while gateway-connected, unmuted, fully idle and without active feedback/playback. |
| `Effective Mute` | Hardware OR software mute; gateway must treat unknown state as muted until first state arrives. |
| `Hardware Mute`, `Software Mute` | Physical mute status and a restorable software mute control. |
| `Voice State` | Hardware-aware displayed state; do not infer cloud session state from media-player idle alone. |
| `set_voice_state(state: string)` | Gateway reports `idle`, `listening`, `thinking`, `speaking`, `error`, or `listening_followup`. `listening` plays start feedback once. |

Button actions are distinct from wake detection. The wake callback never stops playback or resets context. It checks both gateway-requested and displayed `idle` states and reserves `listening` before emitting the event. The gateway must independently reject wake unless its own conversation is idle and mute is known off. Playback completion deliberately does not clear the requested conversation state: the gateway owns the transition through the eight-second `listening_followup` window back to `idle`, so wake cannot reopen or interrupt an active follow-up.

While API-connected and unmuted, the microphone continuously sends audio to the local gateway; idle wake detection does not disable this LAN transport. The gateway must discard idle PCM without retention and open cloud upload only after accepting a button or permitted wake event. Muting stops the detector, voice-assistant capture and microphone, and emits Stop; it restarts capture only after unmuting with an API client connected.

## Configuration checks

Run `esphome config firmware/voice-pe.yaml` after generating the tones and filling in your local secrets. Configuration loads the pinned Voice Kit component and official wake model and resolves the YAML includes and media-file paths. The tone generator checks each WAV's channel count, sample width, rate and frame count after writing. ESPHome may report Voice PE strapping-pin use, deprecated `rgb_order`, and the pinned component's missing optional `synchronous` annotation.

Follow the [build guide](../docs/build-and-run.md) to compile and install the firmware.
