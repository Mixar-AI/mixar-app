# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The ``per_tab_undo`` config key is read as a flag, not as Python truthiness:
a hand-edited ``"false"`` in mixar.json must turn per-tab undo off (review
2026-10-01)."""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

_MODULE = Path(__file__).parents[1] / "src" / "scripts" / "mixar" / "bootstrap" / "per_tab_undo_module.py"


@pytest.fixture
def module(monkeypatch):
    bpy_mod = MagicMock(name="bpy")
    monkeypatch.setitem(sys.modules, "bpy", bpy_mod)
    logging_config = ModuleType("mixar.config.logging_config")
    logging_config.get_logger = lambda name: MagicMock(name=name)
    for name in ("mixar", "mixar.config"):
        monkeypatch.setitem(sys.modules, name, ModuleType(name))
    monkeypatch.setitem(sys.modules, "mixar.config.logging_config", logging_config)
    spec = importlib.util.spec_from_file_location("per_tab_undo_module", _MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, bpy_mod


@pytest.mark.parametrize("raw, flag", [
    (False, False), (True, True), (0, False), (1, True),
    ("false", False), ("False", False), ("off", False), ("0", False), ("no", False),
    ("true", True), ("on", True), ("1", True), (" Yes ", True),
    (None, None), ("maybe", None), ([], None),
])
def test_config_value_as_flag(module, raw, flag):
    mod, _ = module
    assert mod._as_bool(raw) is flag


def test_string_false_turns_it_off(module, monkeypatch):
    mod, bpy_mod = module
    wm = bpy_mod.context.window_manager
    wm.mixar_per_tab_undo = True
    config = ModuleType("mixar.config.config")
    config.get_config = lambda: {"per_tab_undo": "false"}
    monkeypatch.setitem(sys.modules, "mixar.config.config", config)
    assert mod.apply_config() is False
    assert wm.mixar_per_tab_undo is False
