# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A Cinema settings popup shows what its rows just changed.

The Director popups stay open (`BLOCK_KEEP_OPEN`) because they are settings
panels, not menus. But Blender creates every block-button popup with
`can_refresh` false, so nothing rebuilt one after a click: in Depth of Field,
switching it on or picking an f-stop left the old chip lit and the old values
showing until the popup was closed and opened again.

The Cinema overlay and dock blocks now carry `BLOCK_MIXAR_POPUPS_REFRESH`,
and `button_activate_init` creates the popups they open refreshable. Blender
already tags a popup region for a refresh when any button in it finishes
(`button_activate_exit`); the flag is what lets that tag take effect.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EDITORS = ROOT / "src/source/blender/editors"
HEADER = (EDITORS / "include/UI_interface_c.hh").read_text(encoding="utf-8")
HANDLERS = (EDITORS / "interface/interface_handlers.cc").read_text(encoding="utf-8")
OVERLAY = (EDITORS / "space_view3d/view3d_director_overlay.cc").read_text(encoding="utf-8")
DOCK = (EDITORS / "space_view3d/view3d_director_timeline.cc").read_text(encoding="utf-8")
POPUP = (EDITORS / "space_view3d/view3d_director_popup.cc").read_text(encoding="utf-8")


def test_the_flag_is_a_mixar_block_bit_past_upstreams():
    assert "BLOCK_MIXAR_POPUPS_REFRESH = 1 << 29," in HEADER
    # Upstream's block flags stop at 27; 28 is the other Mixar bit.
    assert "BLOCK_NO_ACCELERATOR_KEYS = 1 << 27," in HEADER
    assert "BLOCK_MIXAR_ROUND_ALL = 1 << 28," in HEADER


def test_a_flagged_block_opens_refreshable_popups():
    init = HANDLERS[HANDLERS.index("  if (func || handlefunc) {") :]
    init = init[: init.index("  else if (menufunc) {")]
    assert "(but->block->flag & BLOCK_MIXAR_POPUPS_REFRESH) != 0" in init
    assert "popup_block_create(\n        C, data->region, but, func, handlefunc, arg, nullptr, can_refresh);" in init
    # Never unconditionally: an ordinary block keeps upstream's behaviour.
    assert "arg, nullptr, false);" not in init


def test_blender_already_asks_for_the_refresh_after_a_row_runs():
    """The flag only lets an existing tag take effect."""
    exit_body = HANDLERS[HANDLERS.index("  /* redraw and refresh (for popups) */") :]
    assert "ED_region_tag_refresh_ui(data->region);" in exit_body[:200]


def test_both_cinema_blocks_carry_the_flag():
    for source in (OVERLAY, DOCK):
        begin = source.index("ui::Block *block = ui::block_begin(")
        tail = source[begin : begin + 600]
        assert "ui::block_flag_enable(block, ui::BLOCK_MIXAR_POPUPS_REFRESH);" in tail


def test_the_popups_still_stay_open():
    """Refreshing is the second half of the keep-open contract, not a
    replacement for it."""
    assert "ui::block_flag_enable(block, ui::BLOCK_KEEP_OPEN);" in POPUP
