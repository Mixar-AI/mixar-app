# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A checkpoint read runs only after the Agent Bubble purge is verified, in
the document window picked after it (backend#1914); otherwise it is refused."""

import sys
from types import SimpleNamespace

from helpers import _prepare_restore, _scene  # noqa: E402


def test_restore_picks_the_window_after_the_purge_and_skips_the_pill(tc, monkeypatch):
    purge = sys.modules["mixar.modules.agent_bubble.core.bubble_lifecycle"].close_restored_agent_bubble_windows
    bubble = SimpleNamespace(type='AGENT_BUBBLE')
    pill = SimpleNamespace(screen=SimpleNamespace(is_temporary=False, areas=[bubble]), name="pill")
    closing = SimpleNamespace(screen=None, name="closing")
    main = SimpleNamespace(screen=SimpleNamespace(is_temporary=False, areas=[]), name="main")
    fresh = SimpleNamespace(screen=SimpleNamespace(is_temporary=False, areas=[]), name="fresh")
    wm = tc.bpy.context.window_manager
    wm.windows = [pill, main]
    scene = _scene()
    target, _, _ = _prepare_restore(tc, monkeypatch, scene)
    purge.side_effect = lambda: setattr(wm, "windows", [closing, fresh])
    assert tc.m.restore(scene, target["id"])[0]
    reads = [c for c in tc.bpy.context.temp_override.call_args_list if c.kwargs.get("window") is not None]
    assert reads and reads[-1].kwargs["window"] is fresh


def test_restore_refuses_when_a_bubble_window_survives_the_purge(tc, monkeypatch):
    bubble = SimpleNamespace(type='AGENT_BUBBLE')
    pill = SimpleNamespace(screen=SimpleNamespace(is_temporary=False, areas=[bubble]), name="pill")
    main = SimpleNamespace(screen=SimpleNamespace(is_temporary=False, areas=[]), name="main")
    tc.bpy.context.window_manager.windows = [main, pill]
    scene = _scene()
    target, _, seen = _prepare_restore(tc, monkeypatch, scene)
    before = {i["id"] for i in tc.m.list_checkpoints("sess-1")}
    ok, message = tc.m.restore(scene, target["id"])
    assert not ok and "Agent island" in message
    assert seen == {} and not tc.bpy.ops.wm.recover_auto_save.called
    assert {i["id"] for i in tc.m.list_checkpoints("sess-1")} == before   # no orphaned keep-capture


def test_restore_refuses_when_the_purge_raises(tc, monkeypatch):
    purge = sys.modules["mixar.modules.agent_bubble.core.bubble_lifecycle"].close_restored_agent_bubble_windows
    purge.side_effect = ReferenceError("removed window")
    scene = _scene()
    target, _, seen = _prepare_restore(tc, monkeypatch, scene)
    ok, message = tc.m.restore(scene, target["id"])
    assert not ok and "Agent island" not in message
    assert seen == {}
