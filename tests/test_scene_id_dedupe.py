# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene > Copy of a tab that never chatted duplicates ``mixar_scene_id`` (review
2026-10-02, Codex P2): ``dedupe_scene_ids`` keeps it on the scene created first
(lowest ``session_uid``, whatever the names) and drops it from every copy."""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

_CHAT = Path(__file__).parents[1] / "src" / "scripts" / "mixar" / "modules" / "space_mixie_chat"


@pytest.fixture
def scene_identity(monkeypatch):
    bpy_mod = MagicMock(name="bpy")
    handlers = ModuleType("bpy.app.handlers")
    handlers.persistent = lambda fn: fn
    monkeypatch.setitem(sys.modules, "bpy", bpy_mod)
    monkeypatch.setitem(sys.modules, "bpy.app", MagicMock(name="bpy.app"))
    monkeypatch.setitem(sys.modules, "bpy.app.handlers", handlers)
    stubs = {
        "mixar": ModuleType("mixar"),
        "mixar.config": ModuleType("mixar.config"),
        "mixar.config.logging_config": ModuleType("mixar.config.logging_config"),
        "mixar.modules": ModuleType("mixar.modules"),
        "mixar.modules.common": ModuleType("mixar.modules.common"),
        "mixar.modules.common.scenes_log": ModuleType("mixar.modules.common.scenes_log"),
        "mixar.modules.space_mixie_chat": ModuleType("mixar.modules.space_mixie_chat"),
        "mixar.modules.space_mixie_chat.constants": ModuleType("mixar.modules.space_mixie_chat.constants"),
        "mixar.modules.space_mixie_chat.core": ModuleType("mixar.modules.space_mixie_chat.core"),
    }
    stubs["mixar.config.logging_config"].get_logger = lambda name: MagicMock(name=name)
    stubs["mixar.modules.common.scenes_log"].slog = lambda *a, **k: None
    stubs["mixar.modules.space_mixie_chat.constants"].SessionState = MagicMock()
    stubs["mixar.modules.space_mixie_chat"].__path__ = [str(_CHAT)]
    stubs["mixar.modules.space_mixie_chat.core"].__path__ = [str(_CHAT / "core")]
    for name, mod in stubs.items():
        monkeypatch.setitem(sys.modules, name, mod)
    name = "mixar.modules.space_mixie_chat.core.scene_identity"
    spec = importlib.util.spec_from_file_location(name, _CHAT / "core" / "scene_identity.py")
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, mod)
    spec.loader.exec_module(mod)
    return mod


class _Scene(dict):
    def __init__(self, name, uid, scene_id=None):
        super().__init__()
        self.name, self.session_uid = name, uid
        if scene_id:
            self["mixar_scene_id"] = scene_id


def test_the_copy_loses_the_duplicate_id_even_when_renamed_shorter(scene_identity):
    source = _Scene("Kitchen counter", 10, "uuid-1")
    copy = _Scene("K", 42, "uuid-1")          # renamed shorter than the original
    cleared = scene_identity.dedupe_scene_ids([copy, source])
    assert cleared == ["K"]
    assert source.get("mixar_scene_id") == "uuid-1"
    assert "mixar_scene_id" not in copy


def test_distinct_ids_and_scenes_without_one_are_left_alone(scene_identity):
    a, b, c = _Scene("A", 1, "uuid-a"), _Scene("B", 2, "uuid-b"), _Scene("C", 3)
    assert scene_identity.dedupe_scene_ids([a, b, c]) == []
    assert a["mixar_scene_id"] == "uuid-a" and b["mixar_scene_id"] == "uuid-b"
