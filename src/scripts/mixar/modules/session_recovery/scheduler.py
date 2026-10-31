# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""When to write a save point.

Events (an agent script answered, a turn ended, a generation was imported)
ask for one; the timer asks while the document keeps changing. A save waits
for the burst to settle, never runs while the app is busy, and is spaced by
what the last one cost, so saving takes a bounded share of wall time even on
a scene that takes seconds to write.

Pure Python with an injected clock; ``runtime`` calls ``due`` from a 1 s
timer and ``record_save`` after each write.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Policy:
    settle_s: float = 2.0          # quiet time after the last event
    max_defer_s: float = 60.0      # a continuous burst still saves this often
    min_gap_s: float = 15.0        # never two saves closer than this
    cost_factor: float = 20.0      # ... nor closer than 20x the last save's cost
    timer_s: float = 120.0         # changed document, no events: this often
    retry_s: float = 30.0          # after a failed write


@dataclass
class SavePointScheduler:
    policy: Policy = field(default_factory=Policy)
    last_save_at: float = 0.0
    last_cost_s: float = 0.0
    last_failed_at: float = 0.0
    first_request_at: float = 0.0
    last_request_at: float = 0.0
    reasons: list = field(default_factory=list)
    changes: int = 0

    def reset(self, now: float) -> None:
        """A new document is open: its first save is a full interval away."""
        self.last_save_at = now
        self.first_request_at = self.last_request_at = 0.0
        self.reasons = []
        self.changes = 0

    def request(self, reason: str, now: float) -> None:
        if not self.reasons:
            self.first_request_at = now
        if reason not in self.reasons:
            self.reasons.append(reason)
        self.last_request_at = now

    def note_change(self, count: int = 1) -> None:
        self.changes += count

    def gap_s(self) -> float:
        return max(self.policy.min_gap_s, self.policy.cost_factor * self.last_cost_s)

    def due(self, now: float, *, busy: bool, dirty: bool) -> tuple:
        """``(True, reasons)`` when a save point should be written now."""
        if busy:
            return False, []
        if self.last_failed_at and now - self.last_failed_at < self.policy.retry_s:
            return False, []
        if self.last_save_at and now - self.last_save_at < self.gap_s():
            return False, []
        if self.reasons:
            settled = now - self.last_request_at >= self.policy.settle_s
            overdue = now - self.first_request_at >= self.policy.max_defer_s
            if settled or overdue:
                return True, list(self.reasons)
            return False, []
        if (dirty or self.changes) and now - self.last_save_at >= self.policy.timer_s:
            return True, ["timer"]
        return False, []

    def record_save(self, now: float, cost_s: float, ok: bool) -> None:
        if ok:
            self.last_save_at = now
            self.last_cost_s = max(0.0, float(cost_s))
            self.last_failed_at = 0.0
            self.reasons = []
            self.first_request_at = self.last_request_at = 0.0
            self.changes = 0
        else:
            self.last_failed_at = now
