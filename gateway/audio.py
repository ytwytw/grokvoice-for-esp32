# SPDX-License-Identifier: Apache-2.0
"""Stateful mono signed 16-bit PCM conversion."""
import audioop


class PCM:
    def __init__(self, source_rate, target_rate):
        self.source_rate, self.target_rate = source_rate, target_rate
        self.state = None

    def convert(self, pcm):
        if not isinstance(pcm, bytes) or not pcm or len(pcm) % 2:
            raise ValueError('unaligned PCM')
        output, self.state = audioop.ratecv(pcm, 2, 1, self.source_rate,
                                          self.target_rate, self.state)
        return output
