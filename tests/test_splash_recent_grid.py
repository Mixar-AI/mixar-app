# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The splash lists fill a two-column grid column-first, ceil(n/2) rows."""

from pathlib import Path

import pytest

from mixar.modules.common.utils.ui_utils import two_column_cells


class _Layout:
    def __init__(self):
        self.columns = []
        self.factor = None

    def split(self, factor=0.0):
        self.factor = factor
        return self

    def column(self):
        col = object()
        self.columns.append(col)
        return col


@pytest.mark.parametrize("count, left", [(1, 1), (2, 1), (3, 2), (5, 3), (6, 3)])
def test_cells_fill_left_column_first(count, left):
    layout = _Layout()
    cells = two_column_cells(layout, count)
    assert layout.factor == 0.5
    l_col, r_col = layout.columns
    assert cells == [l_col] * left + [r_col] * (count - left)


def test_no_items_draws_no_grid():
    layout = _Layout()
    assert two_column_cells(layout, 0) == []
    assert layout.columns == []


def test_splash_uses_the_grid_below_the_mode_picker():
    splash = Path("src/scripts/mixar/bootstrap/splash_menu.py").read_text()
    lists = splash[splash.index("def _draw_recent_and_unsaved"):splash.index("class WM_MT_splash")]
    assert "two_column_cells(layout, len(recent))" in lists
    # Unsaved Work heads the lists; Recent Projects follows.
    assert lists.index("draw_splash_unsaved(") < lists.index('"Recent Projects"')
    prompt = Path("src/scripts/mixar/modules/session_recovery/prompt.py").read_text()
    assert "two_column_cells(" in prompt
