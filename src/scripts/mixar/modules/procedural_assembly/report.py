# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Report size discipline (no bpy import).

Compile reports ride back to the backend inside the JSON-RPC result and end
up in LLM context — an uncapped report is a token bomb (the backend caps at
~8 KB per tool result; we stay comfortably under it at the source).
"""

from __future__ import annotations

import json

MAX_REPORT_BYTES = 24_000
MAX_LIST_ITEMS = 60
MAX_ISSUE_ITEMS = 12


def _prune(value, depth: int = 0):
    if isinstance(value, dict):
        return {k: _prune(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        cap = MAX_ISSUE_ITEMS if depth >= 2 else MAX_LIST_ITEMS
        items = [_prune(v, depth + 1) for v in list(value)[:cap]]
        if len(value) > cap:
            items.append(f"...(+{len(value) - cap} more)")
        return items
    if isinstance(value, float):
        return round(value, 6)
    return value


def cap_report(report: dict) -> dict:
    """Prune list bloat; if the report is still oversized, drop the heaviest
    optional sections (per-part stats first) rather than truncating JSON."""
    out = _prune(report)
    for drop in ("parts", "mate_graph", "blocks"):
        if len(json.dumps(out)) <= MAX_REPORT_BYTES:
            break
        if drop in out:
            out[drop] = f"(dropped: report exceeded {MAX_REPORT_BYTES} bytes)"
    return out
