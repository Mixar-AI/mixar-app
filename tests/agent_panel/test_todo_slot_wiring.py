# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The chat's `todo` slot is what fills the Parallel Agents panel.

Nothing else feeds it, and the hook is deliberately wrapped in a bare
``except`` so a mirror failure can never break the chat's own todo rendering.
That makes the wiring silent when it breaks: the panel simply never opens, with
no error anywhere. Pinned here, along with the two turn-lifecycle calls that
keep a card from outliving the turn that made it.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHAT_CORE = (
    ROOT / "src" / "scripts" / "mixar" / "modules" / "space_mixie_chat" / "core"
)
SLOT_PROCESSOR = CHAT_CORE / "slot_processor.py"
SESSION = CHAT_CORE / "session.py"


class TestTodoSlotFeedsThePanel:
    def test_apply_todo_slot_mirrors_to_the_panel(self):
        text = SLOT_PROCESSOR.read_text()
        body = text[text.index("def _apply_todo_slot") :]
        body = body[: body.index("\n    def ")]
        assert "mirror_todo_items" in body, (
            "the todo slot is the panel's only data source"
        )

    def test_the_mirror_is_the_last_thing_the_slot_does(self):
        """The chat's own todo rendering must be complete before the panel is
        told about it — the mirror is best-effort, the chat is not."""
        text = SLOT_PROCESSOR.read_text()
        body = text[text.index("def _apply_todo_slot") :]
        body = body[: body.index("\n    def ")]
        assert body.index("bubble.todo_items.add()") < body.index("mirror_todo_items")

    def test_a_mirror_failure_cannot_break_the_chat(self):
        text = SLOT_PROCESSOR.read_text()
        body = text[text.index("def _apply_todo_slot") :]
        body = body[: body.index("\n    def ")]
        hook = body[body.index("mirror_todo_items") - 400 :]
        assert "try:" in hook and "except Exception" in hook


class TestTurnLifecycle:
    def test_a_new_turn_starts_with_an_empty_panel(self):
        text = SESSION.read_text()
        assert "clear_cards" in text, (
            "cards persist after a turn ends, so a turn that never fans out "
            "would otherwise show the previous turn's agents"
        )
        assert re.search(r"is_active and not was_active", text)

    def test_finalize_turn_settles_running_cards(self):
        text = SLOT_PROCESSOR.read_text()
        body = text[text.index("def finalize_turn") :]
        body = body[: body.index("\nclass ")]
        assert "settle_running" in body, (
            "an aborted turn brings no terminal todo snapshot — without this "
            "a card's elapsed clock ticks forever"
        )


class TestMirrorRunsAgainstTheRealSlot:
    """Drive `_apply_todo_slot` end to end with a fake bubble."""

    def test_a_fan_out_on_the_slot_opens_the_panel(self, monkeypatch):
        SCRIPTS = ROOT / "src" / "scripts"
        if str(SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SCRIPTS))
        from mixar.modules.testing.mock_bpy import install_bpy_mock

        install_bpy_mock()

        from mixar.modules.agent_panel.core import cards as cards_mod
        from mixar.modules.space_mixie_chat.core import slot_processor as sp

        seen = {}

        def fake_mirror(items):
            seen["items"] = [(i.item_id, i.text, i.status) for i in items]
            return len(seen["items"])

        monkeypatch.setattr(cards_mod, "mirror_todo_items", fake_mirror)

        class FakeItem:
            """`_fast_set` writes through ``__setitem__`` — the idprop fast
            path that skips RNA's update callbacks."""

            def __init__(self):
                self.item_id = ""
                self.text = ""
                self.status = 'PENDING'

            def __setitem__(self, key, value):
                setattr(self, key, value)

        class FakeItems(list):
            def add(self):
                item = FakeItem()
                self.append(item)
                return item

            def clear(self):
                del self[:]

        class FakeBubble:
            def __init__(self):
                self.todo_items = FakeItems()

        processor = sp.SlotEventProcessor.__new__(sp.SlotEventProcessor)
        processor._start_loader_timer = lambda: None

        bubble = FakeBubble()
        processor._apply_todo_slot(
            bubble,
            [
                {"id": "0", "text": "Build the back window.", "status": "in_progress"},
                {"id": "1", "text": "Texture the frame.", "status": "pending"},
            ],
        )

        assert seen.get("items"), "the slot never reached the panel mirror"
        assert [i[0] for i in seen["items"]] == ["0", "1"]
        assert seen["items"][0][2] == 'IN_PROGRESS'
