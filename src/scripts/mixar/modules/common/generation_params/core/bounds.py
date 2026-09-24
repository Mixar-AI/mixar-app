# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Catalog numeric bounds → bounds an RNA property can actually hold.

Catalog `min`/`max`/`default` are the BACKEND's limits and can exceed the
range of the C type behind the property they configure — MiniMax H3
publishes `seed` as `min -1 / max 4294967295`, and an `IntProperty` is a C
`int`. Passing one through raises `OverflowError` inside `register_class`,
which loses the WHOLE model group (every param of that model), not just the
offending field. Clamping keeps the rest of the schema usable; the backend
still validates the value it is actually sent.

Imports nothing from `bpy`, so both the N-panel engine and the moodboard's
saved nodes can share one ceiling.
"""

import math

from ..constants import UNBOUNDED_INT_MAX, UNBOUNDED_INT_MIN


def rna_int(value: int) -> int:
    """Clamp to the range an RNA ``IntProperty`` (a C ``int``) can hold."""
    return min(max(int(value), UNBOUNDED_INT_MIN), UNBOUNDED_INT_MAX)


def as_number(value, caster):
    """Best-effort numeric coercion of a catalog bound (`"10"`, `10.0` → 10).

    Returns None when the catalog value is missing or not a number, so the
    caller falls back to the unbounded sentinel instead of raising.
    ``OverflowError`` is that same failure: ``json.loads('1e309')`` is
    ``inf``, and ``int(inf)`` raises it.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return caster(value)
    except (TypeError, ValueError, OverflowError):
        try:
            return caster(float(value))
        except (TypeError, ValueError, OverflowError):
            return None


def _finite_number(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def catalog_int(value, fallback=0) -> int:
    """Truncate ``value`` toward zero, or ``fallback`` when it is not finite.

    ``int(value or 0)`` raises ``OverflowError`` on a non-finite JSON number.
    A schema refresh has to keep going with the fallback instead.
    """
    number = as_number(value or fallback, float)
    if not _finite_number(number):
        return fallback
    return int(number)


def integer_window(low: float, high: float):
    """Inclusive integers inside the C int range, or None when the span is empty.

    ``minimum``/``maximum`` are RNA floats. Past 2**24 a C ``float`` cannot
    hold every integer, so 2147483647 reads back as 2147483648 and assigning
    that ``ceil`` to ``value_integer`` raises ``ValueError``. ``ceil``/``floor``
    keep a fractional catalog bound from admitting an excluded integer
    (``min`` 0.2 stays 1, not 0).
    """
    if not _finite_number(low) or not _finite_number(high) or low > high:
        return None
    snapped_low = rna_int(math.ceil(low))
    snapped_high = rna_int(math.floor(high))
    if snapped_low > snapped_high:
        return None
    return snapped_low, snapped_high


def numeric_bounds(spec: dict, caster, low, high, zero, *, min_round=None, max_round=None):
    """`(min, max, default)` for a numeric param, clamped into [low, high].

    Inverted catalog bounds are ordered rather than left to fail at
    registration, and a default outside the resulting range is pulled into
    it — RNA would reject that too.

    ``min_round``/``max_round`` run after the RNA clamp. Rounding first can
    leave the C int range, and a non-finite input degrades to the sentinel:
    ``int(inf)`` would otherwise drop the whole model group.
    """
    integral = min_round is not None or max_round is not None
    parse = float if integral else caster
    raw_min = as_number(spec.get("min"), parse)
    raw_max = as_number(spec.get("max"), parse)
    raw_default = as_number(spec.get("default"), parse)

    def edge(raw, fallback, rounder):
        if raw is None or (integral and not _finite_number(raw)):
            return fallback
        clamped = min(max(raw, low), high)
        if rounder is None:
            return clamped
        return int(rounder(clamped))

    pmin = edge(raw_min, low, min_round)
    pmax = edge(raw_max, high, max_round)
    if pmin > pmax:
        pmin, pmax = pmax, pmin

    if raw_default is None or (integral and not _finite_number(raw_default)):
        default = zero
    elif integral:
        default = int(raw_default)
    else:
        default = raw_default
    return pmin, pmax, min(max(default, pmin), pmax)


def integer_bounds(spec: dict):
    """Integer catalog bounds snapped onto the RNA int range.

    ``min`` uses ``ceil`` and ``max`` uses ``floor`` so the sidebar admits
    the same integers as the settings popup.
    """
    return numeric_bounds(
        spec,
        float,
        UNBOUNDED_INT_MIN,
        UNBOUNDED_INT_MAX,
        0,
        min_round=math.ceil,
        max_round=math.floor,
    )
