# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The timeline keyframe selection, as operators receive it.

The selection itself lives in the timeline region's C++ runtime, next to the
view and the hover — it is view state, not something a .blend should carry,
and it is the same place the hit rects it refers to are stored. The native
side hands it to Python operators as a comma-separated string, because
Blender's ``IntVectorProperty`` is fixed-size and a selection is not.

It lives in ``core`` rather than beside one operator: three operator modules
now parse it, and an operator module importing another is exactly the kind of
cross-import the UI auto-discovery order cannot promise.
"""

from __future__ import annotations


def parse_indices(text: str) -> list[int]:
    """The indices in *text*, ignoring anything that is not one.

    The string comes from the native timeline, but an operator is callable
    from anywhere — the search, a script, a macro — so it never trusts it.
    """
    indices: list[int] = []
    for part in str(text).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            value = int(part)
        except ValueError:
            continue
        if value >= 0 and value not in indices:
            indices.append(value)
    return indices


def selected_beats(shot, text: str) -> list[int]:
    """The indices in *text* that name a beat *shot* actually has, in order."""
    count = len(getattr(shot, "beats", ()))
    return sorted(index for index in parse_indices(text) if index < count)
