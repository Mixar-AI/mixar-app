# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""``push_undo_step`` (per-tab undo M5): a checkpoint pushed from a timer or a
job callback names the tab it belongs to through
``WindowManager.mixar_undo_push(message, scene=)``; without a scene it names
the context scene (the window's tab), and a build without the RNA function
falls back to ``ed.undo_push``."""

import importlib.util
import pathlib
import sys
import types
from unittest.mock import MagicMock

REPO = pathlib.Path(__file__).resolve().parents[1]
MODULE = REPO / "src/scripts/mixar/modules/common/utils/undo.py"


def _load(bpy_mock):
    sys.modules["bpy"] = bpy_mock
    logging_pkg = types.ModuleType("mixar.config.logging_config")
    logging_pkg.get_logger = lambda name: MagicMock()
    sys.modules.setdefault("mixar", types.ModuleType("mixar"))
    sys.modules.setdefault("mixar.config", types.ModuleType("mixar.config"))
    sys.modules["mixar.config.logging_config"] = logging_pkg
    spec = importlib.util.spec_from_file_location("undo_helper", MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_names_the_given_scene():
    bpy = MagicMock()
    mod = _load(bpy)
    scene = object()
    assert mod.push_undo_step("Import result", scene=scene) is True
    bpy.context.window_manager.mixar_undo_push.assert_called_once_with("Import result", scene=scene)
    bpy.ops.ed.undo_push.assert_not_called()


def test_without_a_scene_names_the_context_scene():
    bpy = MagicMock()
    mod = _load(bpy)
    assert mod.push_undo_step("Assemble Character") is True
    bpy.context.window_manager.mixar_undo_push.assert_called_once_with(
        "Assemble Character", scene=bpy.context.scene)


def test_falls_back_without_the_rna_function():
    bpy = MagicMock()
    del bpy.context.window_manager.mixar_undo_push
    mod = _load(bpy)
    assert mod.push_undo_step("Legacy") is True
    bpy.ops.ed.undo_push.assert_called_once_with(message="Legacy")


def test_no_module_pushes_an_untagged_undo_step():
    """Job and timer results land while the window shows any tab: a bare
    ``bpy.ops.ed.undo_push`` files the step under THAT tab, and the result's own
    tab loses it on its next undo/redo (review 2026-10-02: matgen, lookdev 360).
    Only the helper and the executor's no-RNA fallback may call it."""
    allowed = {"modules/common/utils/undo.py", "modules/space_mixie_chat/core/executor.py"}
    root = REPO / "src/scripts/mixar"
    offenders = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if "/tests/" in rel or rel in allowed:
            continue
        if "ed.undo_push(" in path.read_text(encoding="utf-8", errors="replace"):
            offenders.append(rel)
    assert offenders == []
