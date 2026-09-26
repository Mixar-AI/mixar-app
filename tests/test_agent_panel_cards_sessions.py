# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Parallel scenes: the Parallel Agents panel mirrors ONE tab, the visible one.

A background tab's task list is stored, never drawn over the visible panel;
switching tabs swaps the panel; a run ending in a background tab settles its
own stored cards and leaves the visible panel alone."""

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

_SRC_SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "scripts"))
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)
for _dep in ("keyring", "websocket", "requests", "jwt", "sentry_sdk"):
    sys.modules.setdefault(_dep, MagicMock(name=_dep))

from mixar.modules.agent_panel.core import card_sessions, cards  # noqa: E402


class _Card(SimpleNamespace):
    pass


class _Cards(list):
    def add(self):
        card = _Card(task_id="", name="", task="", status="PENDING", started_at=0.0, ended_at=0.0, dismissing=False)
        self.append(card)
        return card


def _scene(name, sid):
    return SimpleNamespace(name=name, mixie_session_id=sid, mixie_run_open=True)


@pytest.fixture
def rig(monkeypatch):
    wm = SimpleNamespace(mixar_agent_cards=_Cards(), mixar_agent_cards_active=0,
                         mixar_agent_cards_generation=0, windows=[])
    a, b = _scene("A", "sess-a"), _scene("B", "sess-b")
    window = SimpleNamespace(scene=a)
    # Patch the bpy the MODULES hold: the root conftest installs a fresh bpy
    # stub per test file, so sys.modules["bpy"] can be a different object.
    for bpy in {id(cards.bpy): cards.bpy, id(card_sessions.bpy): card_sessions.bpy}.values():
        monkeypatch.setattr(bpy.context, "window_manager", wm, raising=False)
        monkeypatch.setattr(bpy.context, "window", window, raising=False)
        monkeypatch.setattr(bpy.context, "scene", a, raising=False)
        monkeypatch.setattr(bpy.app.timers, "is_registered", lambda fn: True, raising=False)
    monkeypatch.setattr(cards, "_run_open", lambda scene=None: True)
    card_sessions._sessions.clear()
    card_sessions._memory.clear()
    card_sessions._projected_sid = ""
    wm.mixar_agent_cards.clear()
    return SimpleNamespace(wm=wm, a=a, b=b, window=window)


def _items(*rows):
    return [{"id": f"t{i}", "text": text, "status": status} for i, (text, status) in enumerate(rows)]


def test_a_background_tab_never_draws_over_the_visible_panel(rig):
    shown = cards.mirror_todo_items(_items(("Build the island", "in_progress"), ("Cabinets", "pending")), scene=rig.a)
    assert shown == 2 and [c.task_id for c in rig.wm.mixar_agent_cards] == ["t0", "t1"]
    stored = cards.mirror_todo_items(_items(("Rig the arm", "in_progress")), scene=rig.b)
    assert stored == 1
    assert [c.task_id for c in rig.wm.mixar_agent_cards] == ["t0", "t1"]      # A still on screen
    assert [r["task_id"] for r in cards._sessions["sess-b"]] == ["t0"]


def test_switching_tabs_swaps_the_panel_both_ways(rig):
    cards.mirror_todo_items(_items(("Build the island", "in_progress"), ("Cabinets", "pending")), scene=rig.a)
    cards.mirror_todo_items(_items(("Rig the arm", "in_progress")), scene=rig.b)
    rig.window.scene = rig.b
    cards.project_foreground()
    assert [c.task for c in rig.wm.mixar_agent_cards] == ["Rig the arm"]
    rig.window.scene = rig.a
    cards.project_foreground()
    assert [c.task for c in rig.wm.mixar_agent_cards] == ["Build the island", "Cabinets"]
    cards.project_foreground()                                                  # same tab: no-op
    assert rig.wm.mixar_agent_cards_active == 2


def test_a_background_run_ending_settles_its_own_cards_only(rig):
    cards.mirror_todo_items(_items(("Build the island", "in_progress"), ("Cabinets", "pending")), scene=rig.a)
    cards.mirror_todo_items(_items(("Rig the arm", "in_progress")), scene=rig.b)
    cards.settle_running(scene=rig.b)
    assert [c.status for c in rig.wm.mixar_agent_cards] == ["RUNNING", "PENDING"]  # A untouched
    assert cards._sessions["sess-b"][0]["status"] == "FAILED"
    cards.clear_cards(scene=rig.b)                                              # B's new run
    assert "sess-b" not in cards._sessions and len(rig.wm.mixar_agent_cards) == 2


def test_clearing_the_visible_tab_closes_the_panel_and_a_tab_with_nothing_shows_nothing(rig):
    cards.mirror_todo_items(_items(("Build the island", "in_progress"), ("Cabinets", "pending")), scene=rig.a)
    assert cards.clear_cards(scene=rig.a) == 0
    assert len(rig.wm.mixar_agent_cards) == 0 and rig.wm.mixar_agent_cards_active == 0
    cards.mirror_todo_items(_items(("Rig the arm", "in_progress")), scene=rig.b)
    rig.window.scene = rig.b
    cards.project_foreground()
    assert [c.task for c in rig.wm.mixar_agent_cards] == ["Rig the arm"]
    rig.window.scene = rig.a
    cards.project_foreground()
    assert len(rig.wm.mixar_agent_cards) == 0


def test_switching_back_keeps_real_ids_and_running_status(rig):
    """Stored records are card records already: re-projecting them must not
    run them through the todo normalizer again (which knows only todo keys
    and todo statuses — the ids became ``idx:N`` and RUNNING fell to PENDING)."""
    cards.mirror_todo_items(_items(("Build the island", "in_progress"), ("Cabinets", "pending")), scene=rig.a)
    cards.mirror_todo_items(_items(("Rig the arm", "in_progress"), ("Skin", "pending")), scene=rig.b)
    rig.window.scene = rig.b
    cards.project_foreground()
    rig.window.scene = rig.a
    cards.project_foreground()
    assert [(c.task_id, c.status) for c in rig.wm.mixar_agent_cards] == [("t0", "RUNNING"), ("t1", "PENDING")]
    assert [r["task_id"] for r in card_sessions._sessions["sess-a"]] == ["t0", "t1"]


def test_a_dismissal_survives_a_round_trip_through_another_tab(rig):
    cards.mirror_todo_items(_items(("Build the island", "done"), ("Cabinets", "in_progress")), scene=rig.a)
    cards.mirror_todo_items(_items(("Rig the arm", "in_progress"), ("Skin", "pending")), scene=rig.b)
    assert cards.dismiss_card("t0")
    assert [c.task_id for c in rig.wm.mixar_agent_cards] == ["t1"]
    rig.window.scene = rig.b
    cards.project_foreground()
    assert [c.task_id for c in rig.wm.mixar_agent_cards] == ["t0", "t1"]     # B's own t0 shows
    rig.window.scene = rig.a
    cards.project_foreground()
    assert [c.task_id for c in rig.wm.mixar_agent_cards] == ["t1"]           # A's t0 stays dismissed
    # The next snapshot of A still carries t0 as DONE: filtered, not resurrected.
    cards.mirror_todo_items(_items(("Build the island", "done"), ("Cabinets", "in_progress")), scene=rig.a)
    assert [c.task_id for c in rig.wm.mixar_agent_cards] == ["t1"]
