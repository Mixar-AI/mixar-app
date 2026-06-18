# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for operation_history.core.scene_diff — snapshot + diff (pure)."""

import os
import sys

_test_dir = os.path.dirname(os.path.abspath(__file__))
_scripts_dir = os.path.abspath(os.path.join(_test_dir, "..", "..", ".."))  # -> src/scripts
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from types import SimpleNamespace

from mixar.modules.operation_history.core import scene_diff as SD


def _obj(name, loc=(0, 0, 0)):
    return SimpleNamespace(name=name, type="MESH", location=list(loc),
                           rotation_euler=[0, 0, 0], scale=[1, 1, 1], material_slots=[])


def _scene(objs):
    return SimpleNamespace(objects=objs)


def test_diff_detects_created_modified_deleted():
    before = SD.snapshot_scene(_scene([_obj("A"), _obj("B")]))
    after = SD.snapshot_scene(_scene([_obj("A", loc=(1, 0, 0)), _obj("C")]))
    delta = SD.diff_snapshots(before, after)
    assert delta["created"] == ["C"]
    assert delta["deleted"] == ["B"]
    assert delta["modified"] == ["A"]


def test_empty_diff():
    s = SD.snapshot_scene(_scene([_obj("A")]))
    assert SD.diff_snapshots(s, s) == {"created": [], "modified": [], "deleted": []}
