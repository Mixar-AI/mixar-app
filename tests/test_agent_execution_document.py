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
