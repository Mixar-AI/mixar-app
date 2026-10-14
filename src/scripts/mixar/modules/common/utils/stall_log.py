# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Reader for the native main-thread stall log (``WM_stall_monitor.hh``).

The window manager appends one JSON object per stalled main-loop iteration to
``<user config>/mixar/stalls.jsonl``::

    {"t": "2026-10-12T09:30:01Z", "up": 812.4, "seq": 7, "ms": 812,
     "ph": [1, 790, 2, 19], "job": 0, "scopes": 14,
     "top": [{"k": "op", "n": "wm.save_as_mainfile", "ms": 780, "d": 1},
             {"k": "timer", "n": "mod.fn", "ms": 790, "d": 0}],
     "n": {"op": 3, "timer": 2, "draw": 5}}

``ph`` is the phase split in milliseconds (events, handlers, notifiers, draw),
``top`` the longest breadcrumbs of that iteration (longest first, ``d`` is the
nesting depth), ``n`` how many breadcrumbs of each kind ran. This module only
reads; the QA harness and support tooling use it to assert and summarise.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from typing import Iterable

STALL_LOG_NAME = "stalls.jsonl"
PHASES = ("events", "handlers", "notifiers", "draw")


def stall_log_path() -> str:
    """Path the native monitor writes to, honouring ``MIXAR_STALL_LOG``."""
    override = os.environ.get("MIXAR_STALL_LOG", "")
    if override and override not in ("0", "off"):
        return override
    import bpy  # noqa: PLC0415 - optional at import time for tests

    config_dir = bpy.utils.user_resource("CONFIG")
    return os.path.join(config_dir, "mixar", STALL_LOG_NAME)


def parse_lines(lines: Iterable[str]) -> list[dict]:
    """Parse JSONL text into stall records and ``py_stack`` lines; torn lines are skipped."""
    records = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and ("ms" in record or record.get("kind") == "py_stack"):
            records.append(record)
    return records


def _read_all(path: str | None) -> list[dict]:
    path = path or stall_log_path()
    try:
        with open(path, encoding="utf-8") as handle:
            return parse_lines(handle)
    except OSError:
        return []


def attach_stacks(records: list[dict], stacks: Iterable[dict]) -> list[dict]:
    """Give each record the Python stacks captured during its iteration (joined on ``it``)."""
    by_it: dict[int, list[dict]] = defaultdict(list)
    for stack in stacks:
        by_it[int(stack.get("it", -1))].append(stack)
    for record in records:
        found = by_it.get(int(record.get("it", -2)))
        if found:
            record["py_stacks"] = found
    return records


def read_stalls(path: str | None = None, since_seq: int = 0) -> list[dict]:
    """Stall records with ``seq`` greater than ``since_seq``, each carrying the
    ``py_stacks`` the watchdog captured during that iteration; an absent file is empty."""
    rows = _read_all(path)
    records = [r for r in rows if "ms" in r and int(r.get("seq", 0)) > since_seq]
    return attach_stacks(records, (r for r in rows if r.get("kind") == "py_stack"))


def read_stacks(path: str | None = None) -> list[dict]:
    """The watchdog's ``py_stack`` lines, in file order."""
    return [r for r in _read_all(path) if r.get("kind") == "py_stack"]


def python_frame(record: dict) -> str | None:
    """Innermost Python frame of the first stack captured in ``record``'s iteration, or
    None when no stack was captured or the main thread was outside Python (native stall)."""
    for stack in record.get("py_stacks") or []:
        frames = stack.get("stack") or []
        if frames:
            return frames[-1]
    return None


def dominant_phase(record: dict) -> str:
    """Name of the phase that took the longest in ``record``."""
    phases = record.get("ph") or []
    if len(phases) != len(PHASES):
        return "?"
    return PHASES[max(range(len(PHASES)), key=lambda i: phases[i])]


def culprit(record: dict) -> str:
    """``kind:name`` of the breadcrumb that explains the stall.

    Durations are inclusive, so the deepest breadcrumb that still accounts for
    most of the longest one is the real cause (an agent script run from a timer
    names the operator, not the timer). When no breadcrumb covers a quarter of
    the iteration the cause ran outside every hook and only the phase is known.
    """
    top = record.get("top") or []
    total = float(record.get("ms", 0) or 0)
    if not top or float(top[0].get("ms", 0)) < total * 0.25:
        return f"phase:{dominant_phase(record)}"
    floor = float(top[0].get("ms", 0)) * 0.8
    chosen = max((c for c in top if float(c.get("ms", 0)) >= floor),
                 key=lambda c: int(c.get("d", 0)))
    return f"{chosen.get('k', '?')}:{chosen.get('n', '?')}"


def summarize(records: Iterable[dict]) -> list[dict]:
    """Group records by culprit: count, total and worst milliseconds, worst first."""
    groups: dict[str, dict] = defaultdict(lambda: {"count": 0, "total_ms": 0, "max_ms": 0})
    for record in records:
        key = culprit(record)
        ms = int(record.get("ms", 0))
        group = groups[key]
        group["count"] += 1
        group["total_ms"] += ms
        group["max_ms"] = max(group["max_ms"], ms)
    return [
        {"culprit": key, **values}
        for key, values in sorted(groups.items(), key=lambda kv: -kv[1]["total_ms"])
    ]
