# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The tour is marked seen once its first beat is over, not only at the end,
so a user who quits midway never gets it again on the next launch."""

import ast
from pathlib import Path
from types import SimpleNamespace

from mixar.modules.onboarding.core.tour.session_lifecycle import SessionLifecycleMixin

SESSION = (Path(__file__).resolve().parents[2] / "src" / "scripts" / "mixar" / "modules"
           / "onboarding" / "core" / "tour" / "session.py")


class _Session(SessionLifecycleMixin):
    def __init__(self, index):
        self.runner = SimpleNamespace(index=index)
        self.marks = 0

    def _mark_seen(self):
        self.marks += 1


def test_first_beat_does_not_mark_seen():
    s = _Session(0)
    s._mark_seen_past_first_beat()
    assert s.marks == 0


def test_second_beat_marks_seen_once():
    s = _Session(0)
    s._mark_seen_past_first_beat()
    s.runner.index = 1
    s._mark_seen_past_first_beat()
    s.runner.index = 5
    s._mark_seen_past_first_beat()
    assert s.marks == 1


def test_no_runner_is_a_noop():
    s = _Session(0)
    s.runner = None
    s._mark_seen_past_first_beat()
    assert s.marks == 0


def test_beat_entry_writes_the_seen_flag():
    tree = ast.parse(SESSION.read_text())
    sync = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "_sync_beat")
    calls = {n.func.attr for n in ast.walk(sync)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "_mark_seen_past_first_beat" in calls
