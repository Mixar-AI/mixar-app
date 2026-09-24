# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Microphone level for the live Voice trace.

The island's Voice chip and the Sketch pill draw an ECG-like trace while
dictation records; its height follows ``WindowManager.mixie_chat_voice_level``.
This turns each captured PCM16LE chunk into that 0..1 level: peak dBFS mapped
onto a speech range, rising fast and falling slowly so the trace breathes with
the voice instead of flickering per chunk. Pure (no ``bpy``) so it is tested
directly.
"""

import math
import sys
from array import array

# Peak dBFS mapped to 0 and 1: room tone sits below the floor, raised speech
# near the ceiling.
LEVEL_FLOOR_DB = -50.0
LEVEL_CEILING_DB = -10.0
# Per-chunk smoothing: how much of a louder / quieter chunk is taken at once.
LEVEL_ATTACK = 0.6
LEVEL_RELEASE = 0.25
# Smaller changes are not written back, so steady input costs no RNA writes.
LEVEL_WRITE_EPSILON = 0.02


def pcm16_peak(data):
    """Peak magnitude of little-endian 16-bit mono PCM, 0..1."""
    if not data:
        return 0.0
    usable = len(data) - (len(data) % 2)
    if usable <= 0:
        return 0.0
    samples = array('h')
    samples.frombytes(bytes(data[:usable]))
    if sys.byteorder == 'big':
        samples.byteswap()
    peak = max(max(samples), -min(samples))
    return min(1.0, peak / 32768.0)


def peak_to_level(peak):
    """Map a peak magnitude onto the 0..1 speech range."""
    if peak <= 0.0:
        return 0.0
    db = 20.0 * math.log10(peak)
    span = LEVEL_CEILING_DB - LEVEL_FLOOR_DB
    return min(1.0, max(0.0, (db - LEVEL_FLOOR_DB) / span))


def smooth(previous, target):
    """Rise quickly toward a louder chunk, fall back gently."""
    weight = LEVEL_ATTACK if target > previous else LEVEL_RELEASE
    return previous + (target - previous) * weight


def next_level(previous, data):
    """The published level after one captured chunk."""
    return smooth(previous, peak_to_level(pcm16_peak(data)))


def should_write(published, level):
    """True when the change is large enough to repaint the trace."""
    return abs(level - published) >= LEVEL_WRITE_EPSILON or (level == 0.0 and published != 0.0)
