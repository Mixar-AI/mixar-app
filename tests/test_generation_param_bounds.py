# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Catalog numeric bounds must fit the RNA property behind them.

MiniMax H3 publishes ``seed`` as ``min -1 / max 4294967295`` — the vendor's
real range, but wider than the C ``int`` behind an ``IntProperty``. Passing
it through raised ``OverflowError`` inside ``register_class``, which lost
the ENTIRE ``video_gen/minimax-h3`` group (every param of the model), not
just the seed field.
"""

import struct
import sys
from unittest.mock import patch

import pytest

from mixar.modules.common.generation_params.constants import (
    UNBOUNDED_FLOAT_MAX,
    UNBOUNDED_FLOAT_MIN,
    UNBOUNDED_INT_MAX,
    UNBOUNDED_INT_MIN,
)
from mixar.modules.common.generation_params.core import engine


def _kwargs(param_name, spec):
    """Build one prop and return the kwargs handed to the bpy factory."""
    calls = {}

    def record(**kw):
        calls.update(kw)
        return "PROP"

    props = sys.modules["bpy.props"]
    with patch.object(props, "IntProperty", record), patch.object(
        props, "FloatProperty", record
    ):
        prop, value_map = engine._make_prop(param_name, spec)
    assert prop == "PROP", "expected a numeric property, got %r" % (prop,)
    assert value_map is None
    return calls


# The real MiniMax H3 seed spec, copied from the backend seed migration
# f1c6b8d94a37_seed_minimax_h3_video_catalog.py.
MINIMAX_SEED_SPEC = {
    "type": "integer", "default": -1, "min": -1, "max": 4294967295,
    "label": "Seed", "description": "-1 uses a random seed",
    "widget": "number", "order": 6,
}


def test_minimax_seed_max_is_clamped_to_rna_int_range():
    kwargs = _kwargs("seed", MINIMAX_SEED_SPEC)
    assert kwargs["max"] == UNBOUNDED_INT_MAX
    assert kwargs["min"] == -1
    assert kwargs["default"] == -1


@pytest.mark.parametrize(
    "spec, expected",
    [
        # Bounds below/above the C int range clamp to the sentinels.
        ({"type": "integer", "min": -(2 ** 63), "max": 2 ** 63},
         (UNBOUNDED_INT_MIN, UNBOUNDED_INT_MAX, 0)),
        # An out-of-range default is pulled inside the clamped bounds.
        ({"type": "integer", "default": 4294967295, "max": 4294967295},
         (UNBOUNDED_INT_MIN, UNBOUNDED_INT_MAX, UNBOUNDED_INT_MAX)),
        # A default outside declared bounds never reaches RNA as-is.
        ({"type": "integer", "default": 99, "min": 0, "max": 10}, (0, 10, 10)),
        # Inverted bounds are ordered instead of raising at register time.
        ({"type": "integer", "default": 5, "min": 10, "max": 1}, (1, 10, 5)),
        # Missing bounds keep the unbounded sentinels.
        ({"type": "integer"}, (UNBOUNDED_INT_MIN, UNBOUNDED_INT_MAX, 0)),
        # Numeric strings are still honored; junk degrades, never raises.
        ({"type": "integer", "default": "7", "min": "0", "max": "10"},
         (0, 10, 7)),
        ({"type": "integer", "default": "abc", "min": "n/a"},
         (UNBOUNDED_INT_MIN, UNBOUNDED_INT_MAX, 0)),
        # ceil(min) / floor(max): truncation would admit an excluded integer.
        ({"type": "integer", "min": -1.2, "max": -0.2}, (-1, -1, -1)),
        ({"type": "integer", "min": 0.2, "max": 10, "default": 5}, (1, 10, 5)),
        ({"type": "integer", "min": 0.2}, (1, UNBOUNDED_INT_MAX, 1)),
        # 1e309 is inf. int(inf) raises OverflowError and must not abort.
        ({"type": "integer", "min": 1e309},
         (UNBOUNDED_INT_MIN, UNBOUNDED_INT_MAX, 0)),
        ({"type": "integer", "default": 1e309, "min": 0, "max": 10}, (0, 10, 0)),
    ],
)
def test_integer_bounds(spec, expected):
    kwargs = _kwargs("p", spec)
    assert (kwargs["min"], kwargs["max"], kwargs["default"]) == expected


@pytest.mark.parametrize(
    "spec, expected",
    [
        ({"type": "number", "default": 7.5, "min": 0, "max": "20"},
         (0.0, 20.0, 7.5)),
        ({"type": "float", "default": 1e40, "min": -1e40, "max": 1e40},
         (UNBOUNDED_FLOAT_MIN, UNBOUNDED_FLOAT_MAX, UNBOUNDED_FLOAT_MAX)),
        ({"type": "number"}, (UNBOUNDED_FLOAT_MIN, UNBOUNDED_FLOAT_MAX, 0.0)),
    ],
)
def test_float_bounds(spec, expected):
    kwargs = _kwargs("p", spec)
    assert (kwargs["min"], kwargs["max"], kwargs["default"]) == expected


def test_whole_group_survives_an_out_of_range_param():
    """The regression: one bad bound must not cost the model its schema."""

    class PropertyGroup:  # bpy.types.PropertyGroup is a mock; can't subclass.
        pass

    # Patch through the engine's OWN bpy reference: another test module may
    # have swapped sys.modules["bpy"] for a different stub by now.
    with patch.object(engine.bpy.types, "PropertyGroup", PropertyGroup):
        cls, schema = engine._build_group(
            "video_gen",
            "minimax-h3",
            {
                "prompt": {"type": "string", "default": ""},
                "seed": MINIMAX_SEED_SPEC,
            },
        )
    assert set(schema) == {"prompt", "seed"}
    assert cls.__name__ == "MIXAR_PG_genparams_video_gen__minimax_h3"
    assert schema["seed"]["attr"] == "p_seed"


# ---------------------------------------------------------------------------
# The moodboard node path reads the same catalog bounds into SHARED
# `value_integer` / `minimum` / `maximum` props, so it needs the same ceiling.
# ---------------------------------------------------------------------------


def _c_float(value):
    """Round the way an RNA FloatProperty (a C float) stores a bound."""
    return struct.unpack('f', struct.pack('f', float(value)))[0]


class _RnaIntParam:
    """A node parameter whose `value_integer` behaves like a C int.

    The setter raises ``ValueError``, which is what ``bpy`` raises — not
    ``OverflowError``. ``minimum``/``maximum`` round through C ``float``.
    """

    def __init__(self, minimum, maximum, value=0):
        self.parameter_type = 'INTEGER'
        self.minimum = _c_float(minimum)
        self.maximum = _c_float(maximum)
        self._value = value

    @property
    def value_integer(self):
        return self._value

    @value_integer.setter
    def value_integer(self, value):
        if not UNBOUNDED_INT_MIN <= int(value) <= UNBOUNDED_INT_MAX:
            raise ValueError("value not in 'int' range")
        self._value = int(value)


def test_node_value_clamp_survives_an_out_of_range_catalog_bound():
    from mixar.modules.moodboard.ui import moodboard_graph_param_callbacks as cb

    # A max above the C int range is simply unreachable — no assignment.
    param = _RnaIntParam(-1, 4294967295, value=1234)
    cb._clamp_parameter_value(param)
    assert param.value_integer == 1234

    # A min above it would otherwise be assigned straight into the property.
    param = _RnaIntParam(4294967295, 4294967295, value=0)
    cb._clamp_parameter_value(param)
    assert param.value_integer == UNBOUNDED_INT_MAX

    # 2147483647 is legal, but the C float stores 2147483648.
    param = _RnaIntParam(2147483647, 4294967295, value=0)
    cb._clamp_parameter_value(param)
    assert param.value_integer == UNBOUNDED_INT_MAX

    # Fractional catalog bounds snap with ceil/floor, not int() truncation.
    param = _RnaIntParam(0.2, 10, value=0)
    cb._clamp_parameter_value(param)
    assert param.value_integer == 1


def test_node_default_clamps_to_the_rna_int_range():
    from mixar.modules.moodboard.core import node_schema

    param = _RnaIntParam(-1, 4294967295)
    node_schema._assign_default(
        param, {"type": "integer", "default": 4294967295}, [], None
    )
    assert param.value_integer == UNBOUNDED_INT_MAX

    param = _RnaIntParam(-1, 4294967295)
    node_schema._assign_default(param, {"type": "integer", "default": -1}, [], None)
    assert param.value_integer == -1

    # 1e309 is inf. int(inf) must not escape and strand the node schema.
    param = _RnaIntParam(-1, 10, value=4)
    node_schema._assign_default(param, {"type": "integer", "default": 1e309}, [], None)
    assert param.value_integer == 0
