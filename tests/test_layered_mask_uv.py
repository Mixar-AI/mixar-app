# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Repeated texture UVs must not expand a 1K geometry mask into UDIM maps."""
import importlib.util
from pathlib import Path
import numpy as np
import pytest

path = Path(__file__).resolve().parents[1] / 'src/scripts/mixar/modules/paint/layered_build/mask_uv.py'
spec = importlib.util.spec_from_file_location('mask_uv_pure', path)
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


def test_large_repeating_layout_is_one_tile_without_mutating_shading_uvs():
    uv = np.array([[-164, -156], [164, -156], [164, 158], [-164, 158]], dtype=np.float32)
    before = uv.copy()
    result = M.normalized_mask_uvs(uv)
    assert (result > 0).all() and (result < 1).all()
    np.testing.assert_array_equal(uv, before)
    np.testing.assert_allclose(result[1]-result[0], (0.998, 0), atol=1e-6)
    assert M.normalized_mask_uvs(result) is None


def test_existing_single_tile_layout_is_not_rewritten():
    assert M.normalized_mask_uvs([[0, 0], [1, 0], [0, 1]]) is None


@pytest.mark.parametrize('uv', [[], [[float('nan'), 0]], [[0, float('inf')]]])
def test_invalid_uvs_do_not_enter_bake(uv):
    with pytest.raises(ValueError, match='finite'):
        M.normalized_mask_uvs(uv)
