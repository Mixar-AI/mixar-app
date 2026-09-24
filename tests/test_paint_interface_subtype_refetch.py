# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Pin the Blender 5.1+ interface-subtype contract of ``new_tree_input``.

Blender 5.1+ re-types a node-tree interface item in place when its ``subtype``
changes: the C pointer stays, the refined RNA struct does not, so the wrapper
``interface.new_socket`` returned no longer compares equal to the item
enumerated from ``items_tree``. Every ``check_*_ios`` pass keeps the returned
wrapper in ``valid_inputs`` and deletes any interface input that fails that
membership test -- which silently removed EVERY ``NodeSocketFloatFactor``
input (layer opacity, per-channel intensities, Metallic/Roughness on the root
tree) right after creating it. Symptoms: a second fill layer showed a blend of
both colours (the opacity Math nodes lost their links and fell back to 0.5),
and creating a material raised ``KeyError: "Metallic"``.

``new_tree_input`` must therefore hand back the CURRENT wrapper for the item
after assigning the subtype.

The helpers are exercised from their source (extracted via ``ast``) because
importing the paint package pulls in numpy/mathutils, which the standalone
suite's interpreter does not guarantee.
"""

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
INPUTS_PY = REPO / "src/scripts/mixar/modules/paint/core/io/input_outputs/inputs.py"
FUNCTIONS = ("new_tree_input", "refetch_interface_item")


def _load_helpers():
    source = INPUTS_PY.read_text(encoding="utf-8")
    module = ast.parse(source)
    wanted = [n for n in module.body if isinstance(n, ast.FunctionDef) and n.name in FUNCTIONS]
    assert {n.name for n in wanted} == set(FUNCTIONS), "helper missing from inputs.py"
    namespace = {}
    exec(compile(ast.Module(body=wanted, type_ignores=[]), str(INPUTS_PY), "exec"), namespace)
    return namespace


class _Item:
    """Two wrappers of one interface item: same pointer, different identity."""

    def __init__(self, ptr, subtype="NONE"):
        self._ptr = ptr
        self.subtype = subtype

    def as_pointer(self):
        return self._ptr


class _Interface:
    def __init__(self):
        self.stale = None
        self.current = None

    def new_socket(self, name, description="", in_out="INPUT", socket_type=""):
        # The wrapper handed out at creation time...
        self.stale = _Item(0xABC)
        # ...and the one Blender enumerates after the subtype is reassigned.
        self.current = _Item(0xABC, "FACTOR")
        return self.stale

    @property
    def items_tree(self):
        return [_Item(0x111), self.current, _Item(0x222)]


class _Tree:
    def __init__(self):
        self.interface = _Interface()


@pytest.fixture(scope="module")
def helpers():
    return _load_helpers()


def test_factor_input_returns_the_current_wrapper(helpers):
    tree = _Tree()
    got = helpers["new_tree_input"](tree, ".intensity_value", "NodeSocketFloatFactor")
    assert got is tree.interface.current, "must re-fetch the item after setting the subtype"
    assert got is not tree.interface.stale
    assert tree.interface.stale.subtype == "FACTOR", "the subtype must still be applied"


def test_plain_float_input_is_returned_as_is(helpers):
    tree = _Tree()
    got = helpers["new_tree_input"](tree, "Metallic", "NodeSocketFloat")
    # No subtype change -> no re-typing -> the created wrapper is still valid.
    assert got is tree.interface.stale
    assert tree.interface.stale.subtype == "NONE"


def test_refetch_matches_by_pointer(helpers):
    tree = _Tree()
    tree.interface.new_socket("x")
    assert helpers["refetch_interface_item"](tree, tree.interface.stale) is tree.interface.current
    orphan = _Item(0x999)
    assert helpers["refetch_interface_item"](tree, orphan) is orphan


def test_source_refetches_right_after_the_subtype_assignment():
    """Source-level guard: the re-fetch must directly follow ``inp.subtype = ``."""
    source = INPUTS_PY.read_text(encoding="utf-8")
    module = ast.parse(source)
    fn = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == "new_tree_input")
    src = ast.get_source_segment(source, fn)
    assert "inp.subtype = subtype" in src
    assert src.index("inp.subtype = subtype") < src.index("refetch_interface_item(tree, inp)")
