# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A gated beat must be entered (``_sync_beat``) before its gate is checked.

Beat entry clears flags such as ``viewport_interacted``; checking the gate
first let a scroll during the preceding demo beat satisfy the "your turn" ask
on the tick the runner advanced into it, skipping the pause and dim."""

import ast
from pathlib import Path

SESSION = (Path(__file__).resolve().parents[2] / "src" / "scripts" / "mixar" / "modules"
           / "onboarding" / "core" / "tour" / "session.py")


def _tick_calls():
    tree = ast.parse(SESSION.read_text())
    tick = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "tick")
    calls = [n for n in ast.walk(tick)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
    return sorted(((c.lineno, c.col_offset, c.func.attr) for c in calls))


def test_beat_synced_between_runner_tick_and_gate_check():
    names = [name for _, _, name in _tick_calls()]
    runner_tick = names.index("tick")
    check = names.index("_check_gate")
    assert runner_tick < check
    assert "_sync_beat" in names[runner_tick:check]
