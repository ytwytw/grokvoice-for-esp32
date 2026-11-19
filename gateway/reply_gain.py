# SPDX-License-Identifier: Apache-2.0
"""Fixed PCM gain with a -1 dBFS sample ceiling."""
from array import array
import math
import sys

CEILING = int(32767 * 10 ** (-1 / 20))


def apply_gain(pcm, db):
    if not math.isfinite(db) or not -60 <= db <= 60:
        raise ValueError('reply gain must be finite and in [-60, 60]')
    samples = array('h')
    samples.frombytes(pcm)
    if sys.byteorder != 'little':
        samples.byteswap()
    gain = 10 ** (db / 20)
    samples = array('h', (int(max(-CEILING, min(CEILING, x * gain))) for x in samples))
    if sys.byteorder != 'little':
        samples.byteswap()
    return samples.tobytes()
