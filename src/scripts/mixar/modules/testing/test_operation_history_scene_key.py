# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for operation_history.core.scene_key (persistent per-scene history id)."""

import os
import sys

_test_dir = os.path.dirname(os.path.abspath(__file__))
_scripts_dir = os.path.abspath(os.path.join(_test_dir, "..", "..", ".."))  # -> src/scripts
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from types import SimpleNamespace

from mixar.modules.operation_history.core import scene_key as SK
from mixar.modules.operation_history import constants as C


def test_assigns_and_is_stable():
    s = SimpleNamespace(mixar_op_history_id="")
    a = SK.get_scene_history_id(s)
    assert a                                   # non-empty
    assert s.mixar_op_history_id == a          # persisted onto the scene
    assert SK.get_scene_history_id(s) == a     # stable across calls


def test_existing_id_preserved():
    s = SimpleNamespace(mixar_op_history_id="fixed-id")
    assert SK.get_scene_history_id(s) == "fixed-id"


def test_none_scene_returns_no_session():
    assert SK.get_scene_history_id(None) == C.NO_SESSION
