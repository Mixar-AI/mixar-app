# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import ast
import sys
from unittest.mock import MagicMock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC_SCRIPTS = ROOT / "src" / "scripts"
if str(SRC_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SRC_SCRIPTS))

sys.modules.setdefault("bl_ui", MagicMock())
sys.modules.setdefault("bl_ui.space_toolsystem_common", MagicMock())


def _function_counts(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    counts = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            counts[node.name] = counts.get(node.name, 0) + 1
    return counts


def test_properties_handlers_keeps_single_msgbus_definition():
    counts = _function_counts(
        ROOT / "src/scripts/mixar/modules/uv_editor/ui/properties_handlers.py"
    )

    for name in (
        "_on_active_udim_tile_change",
        "_msgbus_load_post",
        "_register_msgbus",
        "_unregister_msgbus",
    ):
        assert counts.get(name) == 1


def test_snap_base_applies_handles_single_and_multi_value_enums():
    from mixar.modules.uv_editor.ui.base.panels import snap_base_applies

    assert snap_base_applies("VERTEX") is True
    assert snap_base_applies("INCREMENT") is False
    assert snap_base_applies({"VERTEX", "EDGE"}) is True
    assert snap_base_applies({"INCREMENT", "GRID"}) is False


def test_active_uv_tool_override_uses_area_owner_window():
    source = (
        ROOT / "src/scripts/mixar/modules/uv_editor/ui/properties_handlers.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    get_active_tool = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_get_active_uv_tool"
    )

    temp_overrides = [
        node for node in ast.walk(get_active_tool)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "temp_override"
    ]

    assert temp_overrides
    assert any(
        any(keyword.arg == "window" for keyword in call.keywords)
        and any(keyword.arg == "screen" for keyword in call.keywords)
        for call in temp_overrides
    )
