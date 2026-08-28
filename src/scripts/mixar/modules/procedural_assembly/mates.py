# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mate macro library: both halves of every static joint from ONE nominal.

For a mate with nominal ``d`` and fit class ``fit``:

- ``male_solids(type, d, fit)`` returns solids in MATE-FRAME coordinates
  (+Z toward the partner, origin on the part's contact plane). The compiler
  transforms them by the part's local frame and unions them into the part
  BEFORE placement, so the feature is part of the part's own solid.
- ``female_solids(type, d, fit)`` returns CUTTER solids in the PARTNER's
  mate-frame coordinates (+Z out of the partner; the cavity extends into
  -Z). The compiler positions them at the partner frame in world space and
  subtracts them from the partner object.

Both halves derive from the same ``d`` plus the signed fit offset — an edit
to the shared parameter can never orphan one side (paper Sec. 3.1, rule 1).
Kinematic mates (revolute/prismatic/spherical) emit no geometry.

Pure data (no bpy import) — realization happens in the compiler.
"""

from __future__ import annotations

from . import spec


def fit_offset_m(fit: str) -> float:
    return spec.FIT_OFFSET_MM[fit] / 1000.0


def engagement_depth(mate_type: str, d: float) -> float:
    """How far the male half reaches past the interface plane (metres).
    Zero for surface-contact mates and kinematic mates."""
    return {
        "peg_socket": 0.9 * d,
        "press_fit": 0.8 * d,
        "bolt_pattern": _bolt_len(d),
        "flange": 0.12 * d,
        "tab_slot": 0.5 * d,
        "snap_tab": 0.6 * d,
        "lip_rabbet": 0.15 * d,
        "key": 0.9 * d,
    }.get(mate_type, 0.0)


def _bolt_dia(d: float) -> float:
    return max(d / 8.0, 0.003)


def _bolt_len(d: float) -> float:
    return 2.5 * _bolt_dia(d)


def _bolt_ring(d: float, dia: float, length: float, op: str, count: int = 4):
    """Bolt studs/holes on a circle of diameter ``d``, reaching +Z."""
    import math

    out = []
    for i in range(count):
        a = 2.0 * math.pi * i / count + math.pi / 4.0
        out.append({
            "kind": "cylinder", "op": op, "d": dia, "h": length,
            "at": (d / 2.0 * math.cos(a), d / 2.0 * math.sin(a), length / 2.0),
        })
    return out


def male_solids(mate_type: str, d: float, fit: str) -> list[dict]:
    if mate_type not in spec.STATIC_MATE_TYPES:
        return []
    L = engagement_depth(mate_type, d)
    if mate_type == "seat_face":
        return []
    if mate_type in ("peg_socket", "press_fit"):
        lead = 0.15 * L if mate_type == "peg_socket" else 0.0
        body = L - lead
        solids = [{
            "kind": "cylinder", "op": "add", "d": d, "h": body,
            "at": (0.0, 0.0, body / 2.0),
        }]
        if lead > 0:  # chamfered self-centering tip
            solids.append({
                "kind": "cone", "op": "add", "d1": d, "d2": 0.7 * d, "h": lead,
                "at": (0.0, 0.0, body + lead / 2.0),
            })
        return solids
    if mate_type == "bolt_pattern":
        return _bolt_ring(d, _bolt_dia(d), _bolt_len(d), "add")
    if mate_type == "flange":
        t = 0.12 * d
        return [{
            "kind": "cylinder", "op": "add", "d": d, "h": t,
            "at": (0.0, 0.0, t / 2.0),
        }] + _bolt_ring(0.75 * d, _bolt_dia(0.75 * d), _bolt_len(0.75 * d) + t, "add")
    if mate_type == "tab_slot":
        t = 0.25 * d
        return [{
            "kind": "box", "op": "add", "size": (d, t, L),
            "at": (0.0, 0.0, L / 2.0),
        }]
    if mate_type == "snap_tab":
        t = 0.2 * d
        lip = 0.1 * d
        return [
            {"kind": "box", "op": "add", "size": (d, t, L),
             "at": (0.0, 0.0, L / 2.0)},
            # catch lip proud of the tab face near the tip
            {"kind": "box", "op": "add", "size": (d, lip, 0.25 * L),
             "at": (0.0, t / 2.0 + lip / 2.0, 0.8 * L)},
        ]
    if mate_type == "lip_rabbet":
        return [{
            "kind": "tube", "op": "add", "d_outer": d, "d_inner": 0.8 * d,
            "h": L, "at": (0.0, 0.0, L / 2.0),
        }]
    if mate_type == "key":
        kw, kh = 0.25 * d, 0.125 * d
        return [
            {"kind": "cylinder", "op": "add", "d": d, "h": L,
             "at": (0.0, 0.0, L / 2.0)},
            {"kind": "box", "op": "add", "size": (kh, kw, L),
             "at": (d / 2.0 + kh / 2.0 - 0.01 * d, 0.0, L / 2.0)},
        ]
    return []


def female_solids(mate_type: str, d: float, fit: str) -> list[dict]:
    """Cutters in the PARTNER's frame coords; cavities extend into -Z (the
    partner's body). Over-cut slightly past the engagement so the floor of a
    bore never coincides exactly with the peg tip (coplanar boolean noise)."""
    if mate_type not in spec.STATIC_MATE_TYPES:
        return []
    f = fit_offset_m(fit)
    L = engagement_depth(mate_type, d)
    over = max(0.002, 0.1 * L)
    depth = L + over
    if mate_type == "seat_face":
        return []
    if mate_type in ("peg_socket", "press_fit"):
        return [{
            "kind": "cylinder", "op": "cut", "d": d + 2.0 * f, "h": depth,
            "at": (0.0, 0.0, -depth / 2.0 + over / 2.0),
        }]
    if mate_type == "bolt_pattern":
        db = _bolt_dia(d) + 2.0 * f
        return [
            {**s, "op": "cut", "d": db,
             "at": (s["at"][0], s["at"][1], -depth / 2.0 + over / 2.0)}
            for s in _bolt_ring(d, db, depth, "cut")
        ]
    if mate_type == "flange":
        t = 0.12 * d
        recess = t / 2.0
        cutters = [{
            "kind": "cylinder", "op": "cut", "d": d + 2.0 * f, "h": recess + over,
            "at": (0.0, 0.0, -(recess + over) / 2.0 + over / 2.0),
        }]
        db = _bolt_dia(0.75 * d) + 2.0 * f
        hole_depth = _bolt_len(0.75 * d) + over
        cutters += [
            {**s, "op": "cut", "d": db, "h": hole_depth,
             "at": (s["at"][0], s["at"][1], -hole_depth / 2.0 + over / 2.0)}
            for s in _bolt_ring(0.75 * d, db, hole_depth, "cut")
        ]
        return cutters
    if mate_type == "tab_slot":
        t = 0.25 * d
        return [{
            "kind": "box", "op": "cut",
            "size": (d + 2.0 * f, t + 2.0 * f, depth),
            "at": (0.0, 0.0, -depth / 2.0 + over / 2.0),
        }]
    if mate_type == "snap_tab":
        t = 0.2 * d
        lip = 0.1 * d
        return [
            {"kind": "box", "op": "cut",
             "size": (d + 2.0 * f, t + 2.0 * f, depth),
             "at": (0.0, 0.0, -depth / 2.0 + over / 2.0)},
            # undercut pocket the lip snaps into
            {"kind": "box", "op": "cut",
             "size": (d + 2.0 * f, t + 2.0 * lip + 2.0 * f, 0.3 * L),
             "at": (0.0, 0.0, -0.85 * L)},
        ]
    if mate_type == "lip_rabbet":
        return [{
            "kind": "tube", "op": "cut",
            "d_outer": d + 2.0 * f, "d_inner": max(0.8 * d - 2.0 * f, 0.01 * d),
            "h": depth, "at": (0.0, 0.0, -depth / 2.0 + over / 2.0),
        }]
    if mate_type == "key":
        kw, kh = 0.25 * d, 0.125 * d
        return [
            {"kind": "cylinder", "op": "cut", "d": d + 2.0 * f, "h": depth,
             "at": (0.0, 0.0, -depth / 2.0 + over / 2.0)},
            {"kind": "box", "op": "cut",
             "size": (kh + 2.0 * f, kw + 2.0 * f, depth),
             "at": (d / 2.0 + kh / 2.0 - 0.01 * d, 0.0, -depth / 2.0 + over / 2.0)},
        ]
    return []
