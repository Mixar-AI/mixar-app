# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Keep the split GPU overlay limited to preserving animated frame selection.

Pixel correctness and allocation reuse are checked by the real-app movie replay.
"""
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]
REL = Path('source/blender/python/gpu/gpu_py_texture.cc')


def test_texture_overlay_only_changes_animated_frame_selection():
    upstream = ROOT / 'upstream' / REL
    if not upstream.is_file():
        pytest.skip('requires the pinned upstream checkout')
    wrapper = ROOT / 'src' / REL
    parts = re.findall(r'#include "(gpu_py_texture/part_\d+\.inc)"', wrapper.read_text())
    assert parts
    text = ''.join((wrapper.parent / part).read_text() for part in parts)
    start = text.index('  /* Mixar: gl_load/movie_frame_update')
    end = text.index('  gpu::Texture *tex = BKE_image_acquire_gpu_texture', start)
    adjustment = text[start:end]
    assert 'BKE_image_is_animated(ima)' in adjustment
    assert 'iuser.framenr = ima->lastframe;' in adjustment
    assert text[:start] + text[end:] == upstream.read_text()
    assert all(len((wrapper.parent / part).read_text().splitlines()) <= 500 for part in parts)
