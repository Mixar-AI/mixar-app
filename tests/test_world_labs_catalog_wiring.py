# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Source-level contracts for catalog-driven World Labs UI and pano threading."""

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_UI = _ROOT / "src/scripts/mixar/modules/moodboard/ui"
_CORE = _ROOT / "src/scripts/mixar/modules/moodboard/core"


def _source(path):
    return path.read_text(encoding="utf-8")


def test_world_labs_controls_have_no_hardcoded_live_model_or_lod_enums():
    legacy_props = _source(_UI / "moodboard_tab_properties.py")
    catalog_props = _source(_UI / "moodboard_catalog_tab_props.py")
    callbacks = _source(_UI / "moodboard_enum_callbacks.py")
    drawer = _source(_UI / "world_labs_drawer.py")

    assert "class MixieMoodboardTabWorldLabsProps" not in legacy_props
    assert "class MixieMoodboardTabWorldLabsProps" in catalog_props
    assert '_get_world_labs_model_items' in catalog_props
    assert 'get_catalog_model_items("world_labs")' in callbacks
    assert 'draw_capability_selector(' in drawer
    assert 'settings_box, tab, "world_labs"' in drawer
    assert "('marble-1.1'" not in catalog_props
    assert "('500k'" not in catalog_props


def test_world_labs_queue_sends_catalog_parameters_under_params():
    source = _source(_CORE / "world_labs_queue.py")
    tree = ast.parse(source)
    submit = next(
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "submit"
    )
    text = ast.get_source_segment(source, submit)
    assert '"params": {"mode": self.mode, "lod": self.lod}' in text
    assert '"mode": self.mode' not in text.replace(
        '"params": {"mode": self.mode, "lod": self.lod}', ""
    )
    assert 'model: str = "marble-1.1"' not in source
    assert 'lod: str = "500k"' not in source


def test_pano_network_download_stays_off_blender_main_thread():
    source = _source(_CORE / "world_labs_queue.py")
    assert "pano_path = _download_pano(pano_url)" in source
    assert "load_image_from_file(pano_path" in source
    assert "load_image_from_url" not in source
    assert "_cleanup_temp_paths(ply_path, glb_path, pano_path)" in source
