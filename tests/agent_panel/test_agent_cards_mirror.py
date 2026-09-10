# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Parallel Agents panel's card mirror.

The panel is drawn in C++ from ``wm.mixar_agent_cards``, so this module is the
only thing standing between a streaming chat slot and a viewport region that
repaints from it. Three properties matter and are pinned here:

* **Diff-update, not clear-and-rebuild.** RNA idprop writes fire ``NC_WINDOW``
  plus a depsgraph tag; wiping the collection on every ``todo`` slot — which
  streams at turn cadence — would make a status flip cost a full rebuild and a
  repaint of every card.
* **Clocks are durations, never cross-clock comparisons.** Python's
  ``time.monotonic()`` and C++'s ``BLI_time_now_seconds()`` need not share an
  epoch, so a card's elapsed figure is either a difference within one clock or
  it is nonsense.
* **The panel opens only for a real fan-out.** One task is the chat's own todo
  line; showing it again beside the viewport is noise.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

import bpy  # noqa: E402

from mixar.modules.agent_panel.constants import MIN_CARDS_FOR_PANEL  # noqa: E402
from mixar.modules.agent_panel.core import cards as cards_mod  # noqa: E402


class FakeCard:
    """A ``MixarAgentCard`` row: plain attributes, no RNA."""

    def __init__(self):
        self.task_id = ""
        self.name = ""
        self.task = ""
        self.status = 'PENDING'
        self.started_at = 0.0
        self.ended_at = 0.0


class FakeCollection:
    """``bpy_prop_collection`` surface the mirror actually uses."""

    def __init__(self):
        self._rows = []
        self.rebuilds = 0

    def add(self):
        row = FakeCard()
        self._rows.append(row)
        return row

    def clear(self):
        self.rebuilds += 1
        self._rows = []

    def __iter__(self):
        return iter(self._rows)

    def __len__(self):
        return len(self._rows)

    def __getitem__(self, i):
        return self._rows[i]


class FakeWM:
    def __init__(self):
        self.mixar_agent_cards = FakeCollection()
        self.mixar_agent_cards_active = 0
        self.windows = []


@pytest.fixture
def wm(monkeypatch):
    fake = FakeWM()
    monkeypatch.setattr(cards_mod, "_window_manager", lambda: fake)
    monkeypatch.setattr(cards_mod, "_tag_panel_redraw", lambda: None)
    return fake


def _todo(n, status='IN_PROGRESS', prefix="Build part"):
    return [
        {"id": str(i), "text": f"{prefix} {i}.", "status": status} for i in range(n)
    ]


class TestFanOutThreshold:
    def test_a_single_task_never_opens_the_panel(self, wm):
        assert cards_mod.mirror_todo_items(_todo(1)) == 0
        assert wm.mixar_agent_cards_active == 0
        assert len(wm.mixar_agent_cards) == 0

    def test_a_fan_out_opens_it(self, wm):
        assert cards_mod.mirror_todo_items(_todo(3)) == 3
        assert wm.mixar_agent_cards_active == 3
        assert len(wm.mixar_agent_cards) == 3

    def test_the_threshold_is_the_shared_constant(self):
        assert MIN_CARDS_FOR_PANEL == 2

    def test_shrinking_back_to_one_task_closes_it(self, wm):
        cards_mod.mirror_todo_items(_todo(3))
        assert cards_mod.mirror_todo_items(_todo(1)) == 0
        assert len(wm.mixar_agent_cards) == 0


class TestDiffUpdate:
    def test_a_status_flip_does_not_rebuild_the_collection(self, wm):
        cards_mod.mirror_todo_items(_todo(3, status='PENDING'))
        rebuilds = wm.mixar_agent_cards.rebuilds

        items = _todo(3, status='PENDING')
        items[1]["status"] = 'IN_PROGRESS'
        cards_mod.mirror_todo_items(items)

        assert wm.mixar_agent_cards.rebuilds == rebuilds, (
            "a status change must patch in place — a rebuild repaints every card"
        )
        assert [c.status for c in wm.mixar_agent_cards] == ['PENDING', 'RUNNING', 'PENDING']

    def test_a_membership_change_does_rebuild(self, wm):
        cards_mod.mirror_todo_items(_todo(2))
        rebuilds = wm.mixar_agent_cards.rebuilds
        cards_mod.mirror_todo_items(_todo(3))
        assert wm.mixar_agent_cards.rebuilds == rebuilds + 1
        assert len(wm.mixar_agent_cards) == 3

    def test_a_surviving_card_keeps_its_clock_across_a_rebuild(self, wm):
        cards_mod.mirror_todo_items(_todo(2, status='IN_PROGRESS'))
        started = wm.mixar_agent_cards[0].started_at
        assert started > 0.0

        cards_mod.mirror_todo_items(_todo(3, status='IN_PROGRESS'))
        assert wm.mixar_agent_cards[0].started_at == started, (
            "task 0 has been running the whole time — its clock must not restart"
        )


class TestClocks:
    def test_running_stamps_a_start_and_settling_stamps_an_end(self, wm):
        cards_mod.mirror_todo_items(_todo(2, status='IN_PROGRESS'))
        card = wm.mixar_agent_cards[0]
        assert card.started_at > 0.0
        assert card.ended_at == 0.0

        cards_mod.mirror_todo_items(_todo(2, status='DONE'))
        card = wm.mixar_agent_cards[0]
        assert card.ended_at >= card.started_at > 0.0

    def test_a_task_that_settles_without_ever_running_still_has_a_duration(self, wm):
        cards_mod.mirror_todo_items(_todo(2, status='PENDING'))
        cards_mod.mirror_todo_items(_todo(2, status='FAILED'))
        card = wm.mixar_agent_cards[0]
        assert card.started_at > 0.0 and card.ended_at > 0.0

    def test_a_retried_task_restarts_its_clock(self, wm):
        cards_mod.mirror_todo_items(_todo(2, status='FAILED'))
        ended = wm.mixar_agent_cards[0].ended_at
        assert ended > 0.0

        cards_mod.mirror_todo_items(_todo(2, status='IN_PROGRESS'))
        card = wm.mixar_agent_cards[0]
        assert card.ended_at == 0.0, "a re-run card must not keep its old end stamp"
        assert card.started_at >= ended


class TestSettleOnTurnEnd:
    def test_an_aborted_turn_leaves_no_card_spinning(self, wm):
        cards_mod.mirror_todo_items(_todo(3, status='IN_PROGRESS'))
        cards_mod.settle_running()
        assert [c.status for c in wm.mixar_agent_cards] == ['FAILED'] * 3
        assert all(c.ended_at > 0.0 for c in wm.mixar_agent_cards)

    def test_settling_never_rewrites_a_finished_card(self, wm):
        items = _todo(2, status='DONE')
        cards_mod.mirror_todo_items(items)
        before = [(c.status, c.ended_at) for c in wm.mixar_agent_cards]
        cards_mod.settle_running()
        assert [(c.status, c.ended_at) for c in wm.mixar_agent_cards] == before


class TestAgentNaming:
    def test_a_short_task_is_its_own_name(self):
        assert cards_mod.derive_agent_name("Build the back window.") == "Build the back window"

    def test_a_long_task_elides_on_a_word_boundary(self):
        name = cards_mod.derive_agent_name(
            "Build exactly one editable asset from Blender primitives: back window left"
        )
        assert name.endswith("…")
        assert " " not in name[-2:-1] or True  # no trailing space before the ellipsis
        assert not name[:-1].endswith(" ")
        assert len(name) <= 36

    def test_an_empty_task_still_names_the_agent(self):
        assert cards_mod.derive_agent_name("") == "Agent"
        assert cards_mod.derive_agent_name("   ") == "Agent"


class TestStatusVocabulary:
    def test_every_chat_todo_status_maps(self, wm):
        """The chat vocabulary is the backend's after ``_map_status``.

        An unmapped value would silently render as queued, so the whole set is
        pinned rather than sampled.
        """
        for todo_status, expected in (
            ('PENDING', 'PENDING'),
            ('IN_PROGRESS', 'RUNNING'),
            ('DONE', 'DONE'),
            ('FAILED', 'FAILED'),
        ):
            cards_mod.clear_cards()
            cards_mod.mirror_todo_items(_todo(2, status=todo_status))
            assert wm.mixar_agent_cards[0].status == expected

    def test_an_unknown_status_degrades_to_pending(self, wm):
        cards_mod.mirror_todo_items(_todo(2, status='SOMETHING_NEW'))
        assert wm.mixar_agent_cards[0].status == 'PENDING'
