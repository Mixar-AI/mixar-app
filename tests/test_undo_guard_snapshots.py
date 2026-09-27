# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""The undo guard's chat snapshots survive a tab rename.

Every scene tab is auto-named from its first prompt; an undo past that rename
restores the OLD scene name, so a snapshot filed by name would miss and the
tab's transcript would not come back. Snapshots are keyed by session id.
"""

import os
import sys
from types import SimpleNamespace

_SRC_SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "scripts"))
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)


def _scene(name, sid):
    return SimpleNamespace(name=name, mixie_session_id=sid, mixie_chat_messages=[])


def test_snapshots_are_keyed_by_session_then_name(monkeypatch):
    from mixar.modules.space_mixie_chat.core import undo_guard as guard

    a = _scene("Sofa", "sess-a")
    home = _scene("Scene", "")
    monkeypatch.setattr(guard.bpy.data, "scenes", [a, home], raising=False)
    monkeypatch.setattr(guard, "_snapshot_single_scene", lambda s: [f"msgs:{s.name}"])
    snap = guard._snapshot_all_scenes()
    assert snap["session:sess-a"] == ["msgs:Sofa"]
    assert snap["name:Sofa"] == ["msgs:Sofa"]
    assert snap["name:Scene"] == ["msgs:Scene"]
    assert "session:" not in snap


def test_restore_finds_a_renamed_tab_by_its_session(monkeypatch):
    from mixar.modules.space_mixie_chat.core import undo_guard as guard

    restored = []
    monkeypatch.setattr(guard, "_restore_single_scene",
                        lambda scene, snapshot: restored.append((scene.name, snapshot)))
    # The undo put the old name back; the session id survived.
    after_undo = _scene("Scene.001", "sess-a")
    monkeypatch.setattr(guard.bpy.data, "scenes", [after_undo], raising=False)
    guard._restore_all_scenes({"session:sess-a": ["msgs:Sofa"], "name:Sofa": ["msgs:Sofa"]})
    assert restored == [("Scene.001", ["msgs:Sofa"])]


def test_restore_falls_back_to_the_name_for_a_tab_without_session(monkeypatch):
    from mixar.modules.space_mixie_chat.core import undo_guard as guard

    restored = []
    monkeypatch.setattr(guard, "_restore_single_scene",
                        lambda scene, snapshot: restored.append((scene.name, snapshot)))
    monkeypatch.setattr(guard.bpy.data, "scenes", [_scene("Scene", "")], raising=False)
    guard._restore_all_scenes({"name:Scene": ["msgs:Scene"]})
    assert restored == [("Scene", ["msgs:Scene"])]
