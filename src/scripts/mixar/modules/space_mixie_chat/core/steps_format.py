# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure formatting helpers for the agent steps block.

No bpy imports — kept dependency-free so it is unit-testable outside Blender
and reusable by both the slot processor and the dev-data mock.
"""
from collections import Counter
from collections.abc import Iterable

# Kind -> (singular phrase, plural phrase). Declaration order here defines the
# left-to-right order of the rendered summary. Must match the kind enum order
# in chat_slot_types.MixieChatStepItem. First words are lowercase; the joined
# summary's leading character is capitalized in format_steps_summary so a
# standalone non-READ summary (e.g. "wrote 1 file") still reads correctly.
_KIND_PHRASES = [
    ("READ", "read {n} file", "read {n} files"),
    ("WRITE", "wrote {n} file", "wrote {n} files"),
    ("COMMAND", "ran {n} command", "ran {n} commands"),
    ("SEARCH", "ran {n} search", "ran {n} searches"),
    ("TOOL", "used {n} tool", "used {n} tools"),
]

_VALID_KINDS = {entry[0] for entry in _KIND_PHRASES}
_VALID_STATUS = {"PENDING", "RUNNING", "DONE", "FAILED"}


def format_steps_summary(kinds: Iterable[str]) -> str:
    """Build a human summary like "Read 2 files · ran 1 command".

    Args:
        kinds: iterable of kind identifier strings (e.g. "READ", "COMMAND").
            Unknown identifiers are ignored.

    Returns:
        Summary string, or "" when there are no recognized kinds.
    """
    counts = Counter(kinds)
    parts = []
    for kind, singular, plural in _KIND_PHRASES:
        n = counts.get(kind, 0)
        if n <= 0:
            continue
        phrase = (singular if n == 1 else plural).format(n=n)
        parts.append(phrase)
    result = " · ".join(parts)
    return result[:1].upper() + result[1:] if result else ""


def normalize_step_item(item_data: dict) -> dict:
    """Normalize one raw step dict into validated, enum-ready fields.

    Pure (no bpy) so it is unit-testable and shared by _apply_steps_slot and
    the dev-data mock. Coerces kind/status to valid uppercase identifiers
    (defaulting kind->TOOL, status->DONE) and replaces None/missing strings
    with "".

    Returns a dict with keys: item_id, kind, label, target, detail, status.
    """
    kind = (item_data.get("kind") or "tool").upper()
    if kind not in _VALID_KINDS:
        kind = "TOOL"
    status = (item_data.get("status") or "done").upper()
    if status not in _VALID_STATUS:
        status = "DONE"
    return {
        "item_id": item_data.get("id") or "",
        "kind": kind,
        "label": item_data.get("label") or "",
        "target": item_data.get("target") or "",
        "detail": item_data.get("detail") or "",
        "status": status,
    }
