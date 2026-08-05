# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pure grouping keys for selection suggestions: name stems and geometry
signatures. No bpy — unit-testable outside Blender.

Two complementary keys group "the same kind of part":

- geometry signature — identical topology + dimensions. Catches mirrored /
  duplicated parts regardless of naming (the 8 stool legs each have their
  OWN mesh datablock, so linked-duplicate detection finds nothing; vertex
  count + rounded dimensions groups them instantly).
- name stem — the name with directional/index tokens stripped. Catches
  semantic siblings that differ geometrically (a fridge's upper and lower
  doors), and survives only when authors name things; garbage names like
  Cube.001 simply produce low-value stems and the signature key carries.
"""

import re

from ..constants import DIM_ROUND_DECIMALS, STEM_DROP_TOKENS

# Trailing Blender duplicate suffix: ".001", ".014", ...
_DUP_SUFFIX_RE = re.compile(r"\.\d+$")
# Token splitter: underscores, dots, dashes, spaces.
_TOKEN_SPLIT_RE = re.compile(r"[\s_.\-]+")


def name_stem(name):
    """Semantic stem of an object name, lowercase.

    Strips the ``.NNN`` duplicate suffix, then drops directional tokens
    (left/right/front/rear/...), pure numbers, and single letters. Token
    order is preserved. Falls back to the full de-suffixed name when
    stripping would leave nothing.

    ``Stool_Leg_Front_Left.001`` -> ``stool leg``
    ``Left_Drawer_Stack_Drawer_1_Finger_Lip`` -> ``drawer stack drawer finger lip``
    """
    base = _DUP_SUFFIX_RE.sub("", name or "").lower()
    tokens = [t for t in _TOKEN_SPLIT_RE.split(base) if t]
    kept = [t for t in tokens if t not in STEM_DROP_TOKENS and not t.isdigit()]
    return " ".join(kept) if kept else " ".join(tokens)


def geometry_signature(obj_type, dims, counts=None):
    """Hashable signature for "geometrically the same part".

    *obj_type* is the Blender object type string, *dims* the object's local
    dimensions (bounding box * scale — rotation-invariant already), *counts*
    an optional tuple of topology counts (verts/edges/polys for meshes,
    splines/points for curves). Dimensions are rounded to absorb float noise
    between mirrored duplicates.
    """
    rounded = tuple(round(float(d), DIM_ROUND_DECIMALS) for d in (dims or ()))
    return (obj_type, tuple(counts or ()), rounded)


def pretty_label(name):
    """Human label for chip text: drop duplicate suffix and 'Root' tail,
    underscores to spaces. ``Modern_Bar_Stool_Root.001`` -> ``Modern Bar Stool``."""
    base = _DUP_SUFFIX_RE.sub("", name or "")
    base = re.sub(r"[\s_]*[Rr]oot$", "", base)
    return base.replace("_", " ").strip() or name
