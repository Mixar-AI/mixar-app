# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Document fencing survives Blender's nonpersistent-handler reset on load."""

from types import SimpleNamespace

import pytest

from mixar.modules.common.agent_execution import document


@pytest.fixture
def runtime(monkeypatch):
    def persistent(fn):
        monkeypatch.setattr(fn, "_bpy_persistent", True, raising=False)
        return fn

    handlers = SimpleNamespace(load_post=[], undo_post=[], redo_post=[], persistent=persistent)
    wm_type = type("WindowManager", (), {})
    bpy = SimpleNamespace(app=SimpleNamespace(handlers=handlers),
                          types=SimpleNamespace(WindowManager=wm_type))
    monkeypatch.setattr(document, "_bpy", lambda: bpy)
    monkeypatch.setattr(document, "_registered", False)
    monkeypatch.setattr(document, "_document_epoch", 0)
    return bpy


def callbacks():
    return (("load_post", document._on_load_post),
            ("undo_post", document._on_undo_post),
            ("redo_post", document._on_redo_post))


def load_file(runtime):
    # BPY_app_handlers_reset(false) retains only functions carrying this marker.
    for name, _ in callbacks():
        handlers = getattr(runtime.app.handlers, name)
        handlers[:] = [fn for fn in handlers if hasattr(fn, "_bpy_persistent")]
    for fn in runtime.app.handlers.load_post:
        fn(None)


def test_loads_preserve_all_epoch_callbacks(runtime):
    runtime.app.handlers.load_post.append(lambda *_: None)
    document.register()
    for expected_epoch in (1, 2):
        load_file(runtime)
        assert document.document_epoch() == expected_epoch
        for name, fn in callbacks():
            assert getattr(runtime.app.handlers, name) == [fn]
    runtime.app.handlers.undo_post[0](None)
    runtime.app.handlers.redo_post[0](None)
    assert document.document_epoch() == 4


def test_register_repairs_missing_callbacks_without_duplicates(runtime):
    document.register()
    runtime.app.handlers.undo_post.clear()
    delattr(runtime.types.WindowManager, document.WM_RUN_ACTIVE_PROP)
    assert document._registered
    document.register()
    document.register()
    assert hasattr(runtime.types.WindowManager, document.WM_RUN_ACTIVE_PROP)
    for name, fn in callbacks():
        assert getattr(runtime.app.handlers, name) == [fn]
    assert document.document_epoch() == 0


def test_unregister_removes_only_our_callbacks_and_can_register_again(runtime):
    document.register()
    other = lambda *_: None
    runtime.app.handlers.load_post.append(other)
    document.unregister()
    document.unregister()
    assert not document._registered
    assert not hasattr(runtime.types.WindowManager, document.WM_RUN_ACTIVE_PROP)
    assert runtime.app.handlers.load_post == [other]
    assert runtime.app.handlers.undo_post == runtime.app.handlers.redo_post == []
    document.register()
    assert runtime.app.handlers.load_post == [other, document._on_load_post]
    load_file(runtime)
    assert document.document_epoch() == 1


_NEXT_UID = [100]


class _Scene:
    def __init__(self, name, session_uid=None):
        self.name = name
        self._props = {}
        if session_uid is None:
            _NEXT_UID[0] += 1
            session_uid = _NEXT_UID[0]
        self.session_uid = session_uid

    def get(self, key, default=None):
        return self._props.get(key, default)

    def __setitem__(self, key, value):
        self._props[key] = value


def test_per_tab_undo_bumps_only_that_scenes_epoch(monkeypatch):
    monkeypatch.setattr(document, "_document_epoch", 0)
    monkeypatch.setattr(document, "_scene_epochs", {})
    a, b = _Scene("A"), _Scene("B")
    assert document.document_epoch(a) == document.document_epoch(b) == 0
    monkeypatch.setattr(document, "_last_walk_was_per_tab", lambda bpy=None: True)
    document._on_undo_post(a)
    assert document.document_epoch(a) == 1
    assert document.document_epoch(b) == 0          # B's run is not revoked by A's undo
    assert document.document_epoch() == 0           # the shared base did not move
    monkeypatch.setattr(document, "_last_walk_was_per_tab", lambda bpy=None: False)
    document._on_undo_post(a)                       # a document-wide walk
    assert document.document_epoch(a) == 2 and document.document_epoch(b) == 1


def test_scene_epoch_key_survives_a_rename(monkeypatch):
    """Review 2026-09-30, finding 5: the key was the scene id OR the name, and
    the id was only assigned at commit-fence time, so a tab renamed before its
    first commit read epoch 0 again after an undo. The key is the Scene's
    session_uid (review 2026-10-02): a rename keeps it."""
    monkeypatch.setattr(document, "_document_epoch", 0)
    monkeypatch.setattr(document, "_scene_epochs", {})
    monkeypatch.setattr(document, "_last_walk_was_per_tab", lambda bpy=None: True)
    a = _Scene("A")
    document._on_undo_post(a)
    assert document.document_epoch(a) == 1
    a.name = "A renamed"
    assert document.document_epoch(a) == 1            # the rename changed nothing
    document._on_undo_post(a)
    assert document.document_epoch(a) == 2


def test_a_scene_copy_does_not_share_the_originals_epoch(monkeypatch):
    """Review 2026-10-02 (Codex P2): Scene > Copy duplicates ``mixar_scene_id``;
    keyed on it, undoing the copy bumped the original's epoch and its run's
    commit fence answered stale_epoch. The copy has its own session_uid."""
    monkeypatch.setattr(document, "_document_epoch", 0)
    monkeypatch.setattr(document, "_scene_epochs", {})
    monkeypatch.setattr(document, "_last_walk_was_per_tab", lambda bpy=None: True)
    original, copy = _Scene("Source"), _Scene("Source.001")
    original[document.SCENE_ID_PROP] = copy[document.SCENE_ID_PROP] = "same-uuid"
    document._on_undo_post(copy)
    assert document.document_epoch(copy) == 1
    assert document.document_epoch(original) == 0


def test_scene_epoch_falls_back_to_the_name_without_a_session_uid(monkeypatch):
    monkeypatch.setattr(document, "_document_epoch", 0)
    monkeypatch.setattr(document, "_scene_epochs", {})
    monkeypatch.setattr(document, "_last_walk_was_per_tab", lambda bpy=None: True)

    a = _Scene("A", session_uid=0)
    document._on_undo_post(a)
    assert document.document_epoch(a) == 1
