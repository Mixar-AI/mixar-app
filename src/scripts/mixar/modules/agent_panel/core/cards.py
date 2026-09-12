# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The one writer of the ``wm.mixar_agent_cards`` mirror.

The chat's ``todo`` slot carries the running turn's task list — the same list
the orchestrator fans out to parallel agents (``emit_todo`` in the backend,
one entry per ``Task``). ``slot_processor._apply_todo_slot`` hands it here and
this module projects it onto the WindowManager mirror the C++ Parallel Agents
panel draws from.

**Diff-update, never clear-and-rebuild.** RNA idprop writes fire ``NC_WINDOW``
plus a depsgraph tag, and todo slots stream at turn cadence; wiping and
re-adding the whole collection on every event — with a redrawing viewport
region now reading it — is a repaint storm. The collection is rebuilt only
when the *membership* changes; a status flip patches one property in place.

Timings are monotonic-clock readings, not wall clock, so the elapsed figure on
a card cannot jump when the system clock is adjusted. They are stamped on
transitions here (the backend streams status, not timing) and carried across a
membership rebuild so a card that survives keeps its clock.
"""

from __future__ import annotations

import time
from typing import Any, Iterable, Optional

import bpy

from mixar.config.logging_config import get_logger

from ..constants import (
    AGENT_NAME_MAXLEN,
    DONE_CARD_DWELL_S,
    DONE_CARD_EXIT_S,
    AGENT_NAME_TARGET_CHARS,
    AGENT_TASK_ID_MAXLEN,
    AGENT_TASK_MAXLEN,
    MIN_CARDS_FOR_PANEL,
)

logger = get_logger(__name__)

#: Chat todo status -> card status. The chat vocabulary is the backend's
#: ``_TODO_STATUS`` after ``SlotTransformer._map_status`` ("completed" -> "done").
_STATUS_FROM_TODO = {
    'PENDING': 'PENDING',
    'IN_PROGRESS': 'RUNNING',
    'DONE': 'DONE',
    'FAILED': 'FAILED',
}

_TERMINAL = frozenset({'DONE', 'FAILED'})

#: Task ids the user clicked away during the current fan-out. ``dismiss_card``
#: removes the row from the mirror, but the backend keeps streaming the same
#: task list, so a later membership rebuild would re-add the card the user just
#: dismissed. Scoped to the fan-out: ``clear_cards`` resets it, so an id is
#: never silently hidden in a later turn (synthetic ``idx:N`` ids recur).
_dismissed_task_ids: set[str] = set()


def derive_agent_name(task_label: str) -> str:
    """A short display name for the agent that owns ``task_label``.

    The backend's todo label is already the task's human-readable head (a
    sentence like "Build the back window left."), so the name is that sentence
    without its terminal punctuation, elided on a word boundary when long.
    Deriving it here keeps naming a client display concern — the wire contract
    is unchanged.
    """
    label = (task_label or "").strip()
    if not label:
        return "Agent"
    label = label.rstrip(" .!?:;,")
    if len(label) <= AGENT_NAME_TARGET_CHARS:
        return label[:AGENT_NAME_MAXLEN]
    head = label[:AGENT_NAME_TARGET_CHARS]
    cut = head.rfind(" ")
    if cut >= AGENT_NAME_TARGET_CHARS // 2:
        head = head[:cut]
    return (head.rstrip(" .!?:;,") + "…")[:AGENT_NAME_MAXLEN]


def _normalize(todo_items: Iterable[Any]) -> list[dict]:
    """Chat todo items (PropertyGroup rows or plain dicts) -> card records."""
    out: list[dict] = []
    for idx, item in enumerate(todo_items or ()):
        if isinstance(item, dict):
            raw_id = item.get("id") or item.get("item_id") or ""
            text = item.get("text") or item.get("task") or ""
            status = item.get("status") or "PENDING"
        else:
            raw_id = getattr(item, "item_id", "") or ""
            text = getattr(item, "text", "") or ""
            status = getattr(item, "status", "PENDING") or "PENDING"
        task_id = (str(raw_id) or f"idx:{idx}")[:AGENT_TASK_ID_MAXLEN]
        text = str(text)[:AGENT_TASK_MAXLEN]
        out.append({
            "task_id": task_id,
            "name": derive_agent_name(text),
            "task": text,
            "status": _STATUS_FROM_TODO.get(str(status).upper(), 'PENDING'),
        })
    return out


def _window_manager() -> Optional[Any]:
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None or not hasattr(wm, "mixar_agent_cards"):
        return None
    return wm


def _bump_generation(wm: Any) -> None:
    """Mark the panel's contents as a NEW fan-out.

    The C++ side resets scroll and replays the slide-in on a change here. It
    cannot work this out for itself: its card list only re-syncs during a
    draw, and draw does not run while the panel is poll-hidden, so between
    turns it still holds the previous turn's cards.
    """
    if hasattr(wm, "mixar_agent_cards_generation"):
        wm.mixar_agent_cards_generation += 1


def _tag_panel_redraw() -> None:
    """Repaint every View3D so the panel follows a card change.

    The panel region is polled, so an appearing or disappearing panel also
    needs the area re-laid-out, not just repainted.
    """
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return
    for window in wm.windows:
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def mirror_todo_items(todo_items: Iterable[Any]) -> int:
    """Project the running turn's task list onto the card mirror.

    Returns the number of cards the panel will show (0 when the turn is not a
    parallel fan-out). Fail-soft: a mirror failure must never break the chat
    slot that called it.
    """
    wm = _window_manager()
    if wm is None:
        return 0

    records = _normalize(todo_items)
    if _dismissed_task_ids:
        # The backend streams the whole task list, including the ones the user
        # dismissed; drop them before the membership diff so a rebuild cannot
        # resurrect a card that was clicked away.
        records = [
            rec for rec in records if rec["task_id"] not in _dismissed_task_ids
        ]
    if len(records) < MIN_CARDS_FOR_PANEL:
        # Not a fan-out. Clear rather than leave a stale single card up.
        return clear_cards()

    now = time.monotonic()
    cards = wm.mixar_agent_cards
    ids_now = [card.task_id for card in cards]
    ids_next = [rec["task_id"] for rec in records]
    # Empty collection: first fan-out. Disjoint ids: a later turn's tasks
    # arrived while FAILED cards from the previous turn were still up —
    # C++ only resets scroll / entrance animation when generation changes.
    if not ids_now or set(ids_now).isdisjoint(ids_next):
        _bump_generation(wm)

    if ids_now != ids_next:
        # Membership changed — rebuild, carrying clocks and in-flight
        # dismissals of surviving cards.
        timings = {
            card.task_id: (card.started_at, card.ended_at) for card in cards
        }
        done_before = {card.task_id: card.status == 'DONE' for card in cards}
        dismissing = {card.task_id: bool(card.dismissing) for card in cards}
        cards.clear()
        for rec in records:
            card = cards.add()
            card.task_id = rec["task_id"]
            card.name = rec["name"]
            card.task = rec["task"]
            card.status = rec["status"]
            started, ended = timings.get(rec["task_id"], (0.0, 0.0))
            was_done = done_before.get(rec["task_id"], False)
            card.started_at = started
            card.ended_at = ended
            card.dismissing = dismissing.get(rec["task_id"], False)
            _stamp_clocks(card, rec["status"], now)
            if rec["status"] == 'DONE' and not was_done and not card.dismissing:
                _schedule_exit(card.task_id)
    else:
        for card, rec in zip(cards, records):
            if card.status != rec["status"]:
                card.status = rec["status"]
                _stamp_clocks(card, rec["status"], now)
                if rec["status"] == 'DONE':
                    _schedule_exit(card.task_id)
            if card.name != rec["name"]:
                card.name = rec["name"]
            if card.task != rec["task"]:
                card.task = rec["task"]

    count = len(records)
    if wm.mixar_agent_cards_active != count:
        wm.mixar_agent_cards_active = count
    _tag_panel_redraw()
    return count


def begin_dismiss(task_id: str) -> bool:
    """Start a user dismissal: mark, animate, then remove.

    Removing the row on the click would make the card vanish from under the
    cursor. The panel watches `dismissing` and plays the same slide-out a
    finished card gets, so this only marks and schedules.
    """
    wm = _window_manager()
    if wm is None or not task_id:
        return False
    card = next((c for c in wm.mixar_agent_cards if c.task_id == task_id), None)
    if card is None:
        return False
    if card.dismissing:
        return True  # already on its way out; a second click is a no-op
    card.dismissing = True
    _schedule_exit(task_id, dwell=0.0)
    _tag_panel_redraw()
    return True


def _schedule_exit(task_id: str, dwell: float = DONE_CARD_DWELL_S) -> None:
    """Remove a card once it has had time to slide out.

    Python owns the removal and C++ owns the slide, timed from its own first
    sighting of the DONE status — the two clocks share no epoch, so they are
    never compared, only given matching durations. The timer re-checks the
    card's status when it fires, so a task that goes DONE and is then re-run
    (a retry) keeps its card.
    """
    if not task_id:
        return

    def _fire():
        wm = _window_manager()
        if wm is None:
            return None
        card = next(
            (c for c in wm.mixar_agent_cards if c.task_id == task_id), None
        )
        if card is not None and (card.dismissing or card.status == 'DONE'):
            dismiss_card(task_id)
        return None

    try:
        bpy.app.timers.register(_fire, first_interval=dwell + DONE_CARD_EXIT_S)
    except Exception:  # noqa: BLE001 — a failed timer just leaves the card up
        logger.debug("Could not schedule card exit for %s", task_id, exc_info=True)


def _stamp_clocks(card: Any, status: str, now: float) -> None:
    """Start the card's clock when it begins, stop it when it settles."""
    if status == 'RUNNING' and card.started_at == 0.0:
        card.started_at = now
    if status in _TERMINAL:
        if card.started_at == 0.0:
            card.started_at = now
        if card.ended_at == 0.0:
            card.ended_at = now
    elif card.ended_at != 0.0:
        # Re-run of a settled task (retry): the clock restarts.
        card.ended_at = 0.0
        card.started_at = now if status == 'RUNNING' else 0.0


def clear_cards() -> int:
    """Close the panel. Returns 0 so callers can ``return clear_cards()``."""
    wm = _window_manager()
    if wm is None:
        return 0
    _dismissed_task_ids.clear()
    if len(wm.mixar_agent_cards) == 0 and wm.mixar_agent_cards_active == 0:
        return 0
    wm.mixar_agent_cards.clear()
    wm.mixar_agent_cards_active = 0
    _bump_generation(wm)
    _tag_panel_redraw()
    return 0


def any_running() -> bool:
    """True while at least one card is still working — drives the clock pump."""
    wm = _window_manager()
    if wm is None:
        return False
    return any(card.status == 'RUNNING' for card in wm.mixar_agent_cards)


def settle_running() -> None:
    """End-of-turn: no card may keep spinning once the turn is over.

    Normal completion already brings a terminal ``todo`` snapshot (the backend
    renders anything not DONE as failed there), so this only bites on abort and
    on a stream that ends without one: a still-RUNNING agent did not finish, and
    saying so is more honest than an elapsed clock that ticks forever.
    """
    wm = _window_manager()
    if wm is None:
        return
    now = time.monotonic()
    changed = False
    for card in wm.mixar_agent_cards:
        if card.status in _TERMINAL:
            continue
        card.status = 'FAILED'
        if card.started_at == 0.0:
            card.started_at = now
        card.ended_at = now
        changed = True
    if changed:
        _tag_panel_redraw()


def dismiss_card(task_id: str) -> bool:
    """Remove one card. Returns False when nothing matched.

    Dismissing the last card closes the panel by itself: the region poll reads
    the count this keeps in step, so there is no separate "hide" state to go
    stale against the collection.
    """
    wm = _window_manager()
    if wm is None or not task_id:
        return False
    cards = wm.mixar_agent_cards
    kept = [
        {
            "task_id": card.task_id,
            "dismissing": card.dismissing,
            "name": card.name,
            "task": card.task,
            "status": card.status,
            "started_at": card.started_at,
            "ended_at": card.ended_at,
        }
        for card in cards
        if card.task_id != task_id
    ]
    if len(kept) == len(cards):
        return False

    _dismissed_task_ids.add(task_id)
    cards.clear()
    for rec in kept:
        card = cards.add()
        for key, value in rec.items():
            setattr(card, key, value)
    wm.mixar_agent_cards_active = len(kept)
    _tag_panel_redraw()
    return True
