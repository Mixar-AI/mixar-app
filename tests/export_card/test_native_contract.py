# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Source-level contracts: the TILE sheet kind agrees across RNA, C++ and
Python, and the Export button / File ▸ Export open the card."""

import re
from pathlib import Path

from mixar.modules.common.sheet import tiles

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
EDITORS = SRC / "source/blender/editors"


def _read(path):
    return Path(path).read_text(encoding="utf-8")


def test_tile_kind_value_matches_rna_and_painter():
    rna = _read(SRC / "source/blender/makesrna/intern/rna_ui_api.cc")
    assert re.search(r'\{19,\s*"TILE"', rna)
    sheet = _read(EDITORS / "interface/interface_mixar_sheet.cc")
    assert "case 19:\n      return MixarCardElement::SheetTile;" in sheet
    assert "element <= MixarCardElement::SheetTile" in sheet
    assert "draw_tile(but, rect);" in sheet
    types = _read(EDITORS / "include/UI_mixar_types.hh")
    assert types.index("SheetTile,") < types.index("Count,")
    assert "interface_mixar_sheet_tiles.cc" in _read(EDITORS / "interface/CMakeLists.txt")
    assert tiles.TILE == 'TILE'


def test_logo_buttons_request_the_full_size_preview():
    """The tile / chip / row painters draw `icon_draw_preview` (the big size);
    a plain button only defers the small one, so without this request every
    logo drew as an empty plate."""
    sheet = _read(EDITORS / "interface/interface_mixar_sheet.cc")
    assert "icon_ensure_deferred(static_cast<const bContext *>(block->evil_C), but->icon, true)" in sheet
    assert "MixarCardElement::SheetTile, MixarCardElement::SheetChip" in sheet


def test_tile_geometry_agrees_with_the_painter():
    header = _read(EDITORS / "interface/interface_mixar_sheet.hh")
    label_h = float(re.search(r"tile_label_h = ([\d.]+)f", header).group(1))
    ring_gap = float(re.search(r"tile_ring_gap = ([\d.]+)f", header).group(1))
    ring_w = float(re.search(r"tile_ring_w = ([\d.]+)f", header).group(1))
    chip_icon = float(re.search(r"chip_icon = ([\d.]+)f", header).group(1))
    chip_gap = float(re.search(r"chip_icon_gap = ([\d.]+)f", header).group(1))
    assert tiles.TILE_LABEL_H == label_h
    assert tiles.TILE_RING_OUT == ring_gap + ring_w + 2
    assert (tiles.CHIP_ICON, tiles.CHIP_ICON_GAP) == (chip_icon, chip_gap)


def test_export_button_and_file_menu_open_the_card():
    zen = _read(SRC / "scripts/mixar/modules/workflow/ui/headers/zen_scene_controls.py")
    assert 'export.operator("mixar.export_card", text="Export", icon="EXPORT")' in zen
    topbar = _read(SRC / "scripts/startup/bl_ui/space_topbar.py")
    assert 'operator("mixar.export_card", text="Export…"' in topbar
    assert "props.target = 'WEB'" in topbar
    assert "MIXAR_PT_web_publish" not in topbar


def test_the_publish_popover_is_retired():
    assert not (SRC / "scripts/mixar/modules/web_publish/ui/panels/web_publish_panel.py").exists()
    assert "MIXAR_PT_web_publish" not in _read(
        SRC / "scripts/mixar/modules/web_publish/core/pipeline.py")


def test_agent_spec_cannot_pin_exporter_kwargs():
    """Pinned kwargs come only from the in-process keyword, never the spec."""
    lane = _read(SRC / "scripts/mixar/modules/space_mixie_chat/core/agent_export.py")
    assert "overrides: dict | None = None" in lane
    assert 'spec.get("overrides")' not in lane and "spec['overrides']" not in lane


def test_module_files_stay_under_500_lines():
    folders = [SRC / "scripts/mixar/modules/export_card", SRC / "scripts/mixar/modules/common/sheet"]
    for folder in folders:
        for path in folder.rglob("*.py"):
            assert len(_read(path).splitlines()) <= 500, path
    for name in ("interface_mixar_sheet.cc", "interface_mixar_sheet_controls.cc",
                 "interface_mixar_sheet_tiles.cc"):
        assert len(_read(EDITORS / "interface" / name).splitlines()) <= 500, name
