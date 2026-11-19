# Build your own Voice PE firmware

This guide builds firmware locally for **Home Assistant Voice Preview Edition**
only. Set up the separate gateway using the [gateway guide](gateway.md). No firmware
binaries are provided; build your own image with your own Wi-Fi and ESPHome encryption key.
The source recipe has not yet passed a firmware compile or a hardware test.

## What you need

- A checkout of this repository and a terminal on macOS or Linux.
- Python **3.12**, including `venv` and `pip`, and Git on your PATH. On Linux,
  your distribution may provide venv support as a separate package.
- Internet access for installation, configuration validation and the first
  compile. An ESP32 toolchain and libraries are downloaded during compilation;
  installing the Python package alone does not install the complete toolchain.
- Your 2.4 GHz Wi-Fi name/password and a new ESPHome native API encryption key.
- A Voice PE with its existing, working XMOS audio firmware when you later
  install this build. This recipe does not bundle or update XMOS firmware.

Use ESPHome **2026.10.2**, the
[pinned upstream release](https://github.com/esphome/esphome/releases/tag/2026.10.2).
Its [Python package metadata](https://github.com/esphome/esphome/blob/2026.10.2/pyproject.toml)
requires Python 3.12 through 3.14; this guide uses 3.12. No Home Assistant
installation, Grok credentials or device connection is needed to build.

## 1. Install the build command

Run every command below from the repository root:

```sh
python3.12 -m venv .venv-firmware
. .venv-firmware/bin/activate
python -m pip install -r requirements-firmware.txt
esphome version
```

The last command must report `Version: 2026.10.2`. In a new terminal, activate
the same virtual environment again. Keep it separate from the gateway environment. The requirements file pins ESPHome; it is
not a complete dependency lock or a promise of bit-for-bit reproducible output.

## 2. Supply your local settings

For a fresh checkout:

```sh
umask 077
cp -n firmware/secrets.example.yaml firmware/secrets.yaml
chmod 600 firmware/secrets.yaml
```

`cp -n` preserves an existing secrets file. Edit these three values in that file:

| Key | Value |
| --- | --- |
| `wifi_ssid` | Your 2.4 GHz Wi-Fi network name |
| `wifi_password` | That network's password |
| `api_encryption_key` | A base64-encoded, randomly generated 32-byte key |

Generate a key locally with:

```sh
python -c 'import base64, secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())'
```

Paste the result into `api_encryption_key` as a quoted YAML string. The separate
gateway will need the same key. Keep secrets, generated source and firmware
images private; they can contain credentials. Local secrets and build directories
are ignored by Git. ESPHome's
[native API documentation](https://esphome.io/components/api/#configuration-variables)
describes the encryption key format.

## 3. Generate tones and validate the recipe

```sh
python firmware/generate-tones.py
esphome config firmware/voice-pe.yaml
```

The generator creates the local WAV feedback assets used by `features.yaml`.
Validation should finish with `Configuration is valid!`. It checks YAML,
components and references; it does not compile, flash or prove audio works.
Do not add `--show-secrets` when saving or sharing validation output.

Inputs are [voice-pe.yaml](../firmware/voice-pe.yaml), its included
`features.yaml`, your local secrets and generated tones. Public dependencies are
the official Voice Kit component at the pinned commit and the sole wake model,
official **Okay Nabu 20241226.3**. See
[firmware provenance](../firmware/PROVENANCE.md) for URLs and recorded hashes.

Validation can already fetch external components and model metadata. The first
compile also needs ESPHome's selected ESP-IDF 5.5.6/compiler packages, audio/runtime
libraries and the model bytes. These are public build downloads, not Grok
service calls. A fresh checkout with empty caches is not an offline build.

## 4. Compile locally

```sh
esphome compile firmware/voice-pe.yaml
```

`compile` builds only. Wait for a successful build before using any output.

With the unchanged device name and no ESPHome build-path environment overrides,
the build tree is `firmware/.esphome/build/grokvoice-pe/`. Find the generated
images after a successful compile:

```sh
find firmware/.esphome/build/grokvoice-pe -type f -name '*.bin'
```

For first USB installation, use the merged **factory** image
(`firmware.factory.bin`) with a tool that accepts it. An OTA/application image
alone is insufficient. Do not compile with `--skip-bootloader`. See the
[pinned ESP32 integration](https://github.com/esphome/esphome/blob/2026.10.2/esphome/components/esp32/__init__.py)
for image formats.

This recipe has **no OTA service or safe mode**; updates also require USB.
Flashing replaces the software on the device. Do not publish your locally built
images.

## 5. Flash over USB

1. Connect the Voice PE to your computer with a USB-C **data** cable.
2. Find its serial port. On Linux it is usually `/dev/ttyACM0`; on macOS it is
   `/dev/cu.usbmodem…` (`ls /dev/cu.usbmodem*`). Disconnect other USB serial
   devices so you pick the right one.
3. Write the factory image to address 0 and verify it. `esptool` is installed
   with ESPHome:

   ```sh
   IMG=$(find firmware/.esphome/build/grokvoice-pe -name firmware.factory.bin | head -1)
   python -m esptool --chip esp32s3 --port /dev/ttyACM0 write-flash 0 "$IMG"
   python -m esptool --chip esp32s3 --port /dev/ttyACM0 verify-flash 0 "$IMG"
   ```

   `verify-flash` must print `Verification successful`. Unplug and replug the
   device, or press reset, to start the new firmware. If the port is busy or
   the chip does not respond, close other serial programs, replug USB and retry.

`esphome upload firmware/voice-pe.yaml --device /dev/ttyACM0` is an alternative
that flashes the same build over USB.

### Restore the stock firmware

To go back to the official Home Assistant firmware, use the official
[Voice PE web installer](https://esphome.github.io/home-assistant-voice-pe/)
in a desktop Chrome or Edge browser with the device on USB.

## 6. Gateway and use are separate

The Python gateway connects to the encrypted native API, handles control entities
and serves reply audio. Follow the [gateway installation guide](gateway.md).
Its offline tests do not establish successful device or live Grok operation.

When the gateway is connected, the transport sends microphone audio over the LAN
while connected and unmuted, including when idle. On-device Okay Nabu does not
make that LAN stream trigger-only. The gateway discards idle audio and opens
cloud upload only after an accepted button or idle, unmuted Okay Nabu trigger.
Hardware mute stops capture. Keep the device and reply-audio service on a trusted LAN.

After building, leave the Python environment with `deactivate`. No device or
gateway process was started by these build commands.
