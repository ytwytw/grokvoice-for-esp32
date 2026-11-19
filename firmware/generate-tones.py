#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Generate original mono PCM feedback tones; no downloaded or spoken assets."""

import math
from pathlib import Path
import struct
import wave

RATE = 16000
# Frequency and duration in seconds; zero frequency is a silent separator.
TONES = {
    "volume_tick": [(1300, 0.025)],
    "mute_on": [(700, 0.09), (0, 0.025), (420, 0.12)],
    "mute_off": [(420, 0.09), (0, 0.025), (700, 0.12)],
    "offline": [(400, 0.12), (0, 0.04), (400, 0.12), (0, 0.04), (250, 0.18)],
    "wake": [(660, 0.075), (0, 0.015), (880, 0.11)],
}


def generate(directory):
    directory.mkdir(exist_ok=True)
    for name, notes in TONES.items():
        samples = []
        for frequency, duration in notes:
            count = round(RATE * duration)
            for index in range(count):
                # Five-millisecond ramps avoid a click at each note boundary.
                envelope = min(1.0, index / 80, (count - index - 1) / 80)
                samples.append(round(5000 * envelope * math.sin(2 * math.pi * frequency * index / RATE)))
        path = directory / f"{name}.wav"
        with wave.open(str(path), "wb") as output:
            output.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
            output.writeframes(struct.pack(f"<{len(samples)}h", *samples))
        with wave.open(str(path), "rb") as check:
            assert check.getparams()[:4] == (1, 2, RATE, len(samples))
            assert len(check.readframes(len(samples))) == len(samples) * 2


if __name__ == "__main__":
    generate(Path(__file__).resolve().parent / "assets")
