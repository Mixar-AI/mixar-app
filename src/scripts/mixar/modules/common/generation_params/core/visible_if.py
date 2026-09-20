# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Encode catalog ``visible_if`` for the native island strips.

The schema lives in-process on the Python engine. Native 3D/Media/Splat
strips iterate RNA and cannot call ``is_param_visible``. Each generated
PropertyGroup therefore carries a hidden JSON string keyed by RNA attribute
(``p_*``), never by hardcoded catalog names. C++ evaluates that table against
live sibling values with Python ``str()`` equality (``True``/``False``, enum
identifiers which are already ``str(choice value)``). Float conditions use
lossless double text after validating that the expected Python spelling can
match a float, avoiding a dependency on Python's repr formatter in C++.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from ..constants import FLOAT_TYPES, VISIBLE_IF_MISSING


def _native_expected(other: Dict[str, Any], expected: Any) -> str | None:
    text = str(expected)
    if other["spec"].get("type") in FLOAT_TYPES and other.get("value_map") is None:
        # Python compares str(float), not numeric equality: 1 and "01" must
        # not match 1.0. Once that contract is checked, use the same lossless
        # double format as C++ (RNA float32 values are promoted by Python).
        try:
            value = float(text)
        except ValueError:
            return None
        if str(value) != text:
            return None
        return format(value, ".17g")
    return text


def encode_visible_if_table(schema: Dict[str, Dict[str, Any]]) -> str:
    """JSON object of RNA-attr conditions for the C++ strip evaluator.

    Params without ``visible_if`` are omitted (visible). A condition that
    names a missing param becomes ``{VISIBLE_IF_MISSING: ""}`` so the strip
    fails closed, matching ``is_param_visible``.
    """
    table: Dict[str, Dict[str, str]] = {}
    for entry in schema.values():
        spec = entry.get("spec") or {}
        condition = spec.get("visible_if")
        if not condition:
            continue
        attr = entry.get("attr")
        if not attr:
            continue
        if not isinstance(condition, dict):
            table[attr] = {VISIBLE_IF_MISSING: ""}
            continue
        inner: Dict[str, str] = {}
        for other_name, expected in condition.items():
            other = schema.get(other_name)
            if other is None or not other.get("attr"):
                inner[VISIBLE_IF_MISSING] = ""
                continue
            native = _native_expected(other, expected)
            if native is None:
                inner[VISIBLE_IF_MISSING] = ""
            else:
                inner[other["attr"]] = native
        table[attr] = inner
    return json.dumps(table, separators=(",", ":"), sort_keys=True, ensure_ascii=True)
