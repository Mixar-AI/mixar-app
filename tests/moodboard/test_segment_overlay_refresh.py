# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Reusing a display Image must publish later masks to the canvas GPU cache."""

from types import SimpleNamespace as NS
from unittest.mock import Mock

import numpy as np

from mixar.modules.moodboard.core.segment_overlay import recomposite_display_image


class Pixels:
    def __init__(self, values):
        self.values = np.asarray(values, dtype=np.float32).flatten()

    def foreach_get(self, target):
        target[:] = self.values

    def foreach_set(self, values):
        self.values = values.copy()


def test_second_mask_changes_reused_image_and_invalidates_cached_pixels():
    source_pixels = np.ones((12, 12, 4), dtype=np.float32)
    source = NS(name='source', size=(12, 12), pixels=Pixels(source_pixels))
    display = NS(pixels=Pixels(source_pixels), update=Mock(), update_tag=Mock(), pack=Mock())
    mask_pixels = source_pixels.copy()
    mask_pixels[:, :, :3] = 0
    mask_pixels[2:8, 2:8, :3] = 1
    mask = NS(size=(12, 12), pixels=Pixels(mask_pixels))
    first = NS(name='Box Segment 1', mask_image=mask, active=True)
    item = NS(image=source, display_image=display, segments=[first])

    recomposite_display_image(item)
    first_pixels = display.pixels.values.copy()
    assert first_pixels.reshape(12, 12, 4)[4, 4, 1] > first_pixels.reshape(12, 12, 4)[4, 4, 0]
    display.update.reset_mock()
    display.update_tag.reset_mock()

    lasso = NS(name='Lasso Segment 2', mask_image=mask, active=True,
               outline_only=True, selection_outline='[[0.1,0.1],[0.8,0.1],[0.8,0.8]]')
    item.segments.append(lasso)
    recomposite_display_image(item)

    assert item.display_image is display  # the warmed Image/texture is reused
    assert not np.array_equal(display.pixels.values, first_pixels)
    np.testing.assert_array_equal(source.pixels.values, source_pixels.flatten())
    display.update.assert_called_once()  # update the byte representation
    display.update_tag.assert_called_once()  # invalidate the native depsgraph stamp

    lasso.active = False
    recomposite_display_image(item)
    np.testing.assert_array_equal(display.pixels.values, first_pixels)
    assert display.update_tag.call_count == 2
