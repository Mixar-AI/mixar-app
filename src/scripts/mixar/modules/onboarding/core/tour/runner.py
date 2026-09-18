# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — the beat state machine.

Pure Python: the clock, the wall time source and the action sink are
injected, so the whole machine runs under pytest with a fake clock.

Contract (per ``tick()``):

1. Apply skip ranges: if the clock sits inside a range, seek to its resume
   point.
2. The current beat is the last one whose ``enter_ms`` <= clock ms — except
   that a gated beat holds the clock at its ``clip_end_ms`` (see 4) even
   though the next beat enters there. Beats the clock jumped over fire
   their actions in order on the way.
3. Fire every action of the current beat whose ``at_ms`` has passed, once.
4. A gated beat pauses the clock at its ``clip_end_ms`` (status ``gated``)
   and arms a wall-clock deadline. ``satisfy_gate()`` (the user did it) or
   the deadline (the tour does it via ``auto_action``) jumps to
   ``gate.advance_to``.
5. The terminal beat ends the tour once its clip end is reached.

User pause is independent of gate pause and freezes gate deadlines.
"""

import time
from typing import Callable, Optional

from .beats import Tour, build_skip_plan, find_index
from .config import TERMINAL_END_SLACK_MS

STATUS_IDLE = "idle"
STATUS_RUNNING = "running"
STATUS_GATED = "gated"
STATUS_ENDED = "ended"


class Clock:
    """Interface the runner drives. See clock.py for implementations."""

    def position_ms(self) -> int: ...
    def pause(self) -> None: ...
    def resume(self) -> None: ...
    def seek_ms(self, ms: int) -> None: ...
    def ended(self) -> bool: ...


class TourRunner:
    def __init__(
        self,
        tour: Tour,
        clock: Clock,
        on_action: Callable[[str, dict], None],
        on_end: Callable[[], None],
        skipped_ids=(),
        wall: Callable[[], float] = time.monotonic,
    ):
        self.tour = tour
        self.beats, self.skip_ranges = build_skip_plan(tour.beats, skipped_ids)
        self.clock = clock
        self.on_action = on_action
        self.on_end = on_end
        self.wall = wall

        self.index = -1
        self.status = STATUS_IDLE
        self.user_paused = False
        self._fired: set = set()
        self._gate_deadline: Optional[float] = None
        self._pause_started: Optional[float] = None
        self._entered_wall: float = 0.0
        self._end_deadline: Optional[float] = None
        self.last_ms = 0

    # -- lifecycle -------------------------------------------------------

    @property
    def beat(self):
        if 0 <= self.index < len(self.beats):
            return self.beats[self.index]
        return None

    def start(self) -> None:
        self.status = STATUS_RUNNING
        self.clock.seek_ms(0)
        self.clock.resume()
        self.tick()

    def end(self) -> None:
        if self.status == STATUS_ENDED:
            return
        self.status = STATUS_ENDED
        try:
            self.clock.pause()
        finally:
            self.on_end()

    # -- ticking ---------------------------------------------------------

    def tick(self) -> None:
        if self.status in (STATUS_IDLE, STATUS_ENDED):
            return
        now = self.wall()
        if self.status == STATUS_GATED:
            if not self.user_paused and self._gate_deadline is not None \
                    and now >= self._gate_deadline:
                self._auto_advance()
            return
        if self.user_paused:
            return

        ms = self.clock.position_ms()
        for r in self.skip_ranges:
            if r.start_ms <= ms < r.resume_ms:
                self.clock.seek_ms(r.resume_ms)
                ms = r.resume_ms
                break
        self.last_ms = ms

        # Walk forward one beat at a time. A gated beat's clip end is where
        # the next beat enters, so the gate must be checked BEFORE the
        # "last beat whose enter_ms <= ms" rule or it could never engage;
        # and a clock jump over several beats must fire what each of them
        # would have done, in order, so app state is what the target expects.
        while True:
            beat = self.beat
            if beat is not None and beat.gate is not None and ms >= beat.clip_end_ms:
                self._fire_due_actions(beat, ms)
                self.clock.pause()
                self.status = STATUS_GATED
                self._gate_deadline = now + beat.gate.auto_advance_wall_ms / 1000.0
                return
            nxt = self.index + 1
            if nxt < len(self.beats) and self.beats[nxt].enter_ms <= ms:
                if beat is not None:
                    self._fire_all_actions(beat)
                self._enter(nxt)
                continue
            break
        if beat is None:
            return
        self._fire_due_actions(beat, ms)

        if self.index == len(self.beats) - 1:
            if ms >= beat.clip_end_ms - TERMINAL_END_SLACK_MS or self.clock.ended():
                if self._end_deadline is None:
                    self._end_deadline = now + beat.end_after_wall_ms / 1000.0
                    self.clock.pause()
                if now >= self._end_deadline:
                    self.end()

    def _enter(self, idx: int) -> None:
        self.index = idx
        self._entered_wall = self.wall()
        self._gate_deadline = None

    def _fire_due_actions(self, beat, ms: int) -> None:
        for i, (at_ms, name, args) in enumerate(beat.actions):
            key = (beat.id, i)
            if key in self._fired or ms < at_ms:
                continue
            self._fired.add(key)
            self.on_action(name, dict(args))

    def _fire_all_actions(self, beat) -> None:
        """Fire whatever ``beat`` has not fired yet, regardless of at_ms —
        used when the tour leaves or passes over a beat."""
        self._fire_due_actions(beat, max(at for at, _n, _a in beat.actions)
                               if beat.actions else 0)

    # -- gates and jumps -------------------------------------------------

    def gate_active(self) -> bool:
        """True while the current beat's gate can still be satisfied."""
        beat = self.beat
        return (beat is not None and beat.gate is not None
                and self.status in (STATUS_RUNNING, STATUS_GATED))

    def satisfy_gate(self) -> bool:
        """The user performed the gate action: jump forward now."""
        if not self.gate_active():
            return False
        self._jump(self.beat.gate.advance_to)
        return True

    def _auto_advance(self) -> None:
        gate = self.beat.gate
        if gate.auto_action is not None:
            name, args = gate.auto_action
            self.on_action(name, dict(args))
        self._jump(gate.advance_to)

    def skip_beat(self) -> None:
        """Controls "Skip step": jump to the next beat (or finish the gate
        the tour's own way when one is pending)."""
        if self.status == STATUS_ENDED:
            return
        if self.gate_active():
            self._auto_advance()
            return
        if self.index >= len(self.beats) - 1:
            self.end()
            return
        self._jump(self.beats[self.index + 1].id)

    def _jump(self, beat_id: str) -> None:
        target = find_index(self.beats, beat_id)
        if target < 0 or target <= self.index:
            # Never jump backwards; treat as a no-op to keep the clock sane.
            self.status = STATUS_RUNNING
            if not self.user_paused:
                self.clock.resume()
            return
        # Fire everything the beat being left and every skipped-over beat
        # would have done, so app state is what the target beat expects (the
        # reference tour does the same through realWindowActions on the
        # resume target).
        for j in range(max(self.index, 0), target):
            self._fire_all_actions(self.beats[j])
        self._gate_deadline = None
        self.status = STATUS_RUNNING
        self.clock.seek_ms(self.beats[target].enter_ms)
        self.last_ms = self.beats[target].enter_ms
        self._enter(target)
        self._fire_due_actions(self.beat, self.last_ms)
        if not self.user_paused:
            self.clock.resume()

    # -- user pause ------------------------------------------------------

    def set_user_paused(self, paused: bool) -> None:
        if paused == self.user_paused or self.status == STATUS_ENDED:
            return
        now = self.wall()
        self.user_paused = paused
        if paused:
            self._pause_started = now
            self.clock.pause()
            return
        if self._pause_started is not None:
            delta = now - self._pause_started
            if self._gate_deadline is not None:
                self._gate_deadline += delta
            if self._end_deadline is not None:
                self._end_deadline += delta
        self._pause_started = None
        if self.status == STATUS_RUNNING:
            self.clock.resume()

    # -- introspection ---------------------------------------------------

    def gate_seconds_left(self) -> Optional[float]:
        if self.status != STATUS_GATED or self._gate_deadline is None:
            return None
        # While the user has paused, the deadline is extended on resume by
        # the paused duration, so the visible countdown must freeze too.
        now = self._pause_started if (self.user_paused and self._pause_started
                                      is not None) else self.wall()
        return max(0.0, self._gate_deadline - now)

    def state(self) -> dict:
        beat = self.beat
        return {
            "tour": self.tour.id,
            "status": self.status,
            "index": self.index,
            "beat": beat.id if beat else "",
            "ms": self.last_ms,
            "paused": self.user_paused,
            "gate": (beat.gate.check if beat and beat.gate else ""),
            "gate_seconds_left": self.gate_seconds_left(),
        }
