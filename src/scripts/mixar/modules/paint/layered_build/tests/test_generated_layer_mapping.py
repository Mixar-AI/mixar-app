# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Every generated base layer must end its bind with the node check.

A COLOR fill layer only becomes vector-using once its channel overrides are
IMAGE, so its **Mapping node** is created by the node check that
``update_layer_channel_override`` runs. Builders bind those overrides under
``mp.halt_update = True``, which blocks that callback -- so they owe the layer
an explicit ``finalize_layer_channel_overrides`` call. Miss it and the layer
ships with every image texture wired straight to the UV input: no Mapping node
and no working UV offset / rotation / scale on a generated material (reported
against a MatGen patina material, 2026-08-29).

``bpy`` is a MagicMock in this suite, so the contract is pinned at source
level; the wiring itself is verified in a real Blender run.
"""

import ast
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[7]
_FINALIZER = "finalize_layer_channel_overrides"

# Every function that binds channel overrides programmatically, i.e. sets
# ch.override* while mp.halt_update is held.
_BINDERS = [
    (
        "src/scripts/mixar/modules/paint/layered_build/pbr_layer.py",
        "_bind_prepared_maps",
    ),
    (
        "src/scripts/mixar/modules/moodboard/core/lookdev360_paint_integration.py",
        "add_lookdev360_fill_layer",
    ),
]


def _function(path: str, name: str):
    tree = ast.parse((_REPO / path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    pytest.fail(f"{name} not found in {path}")


def _calls(func) -> list:
    names = []
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Name):
                names.append(target.id)
            elif isinstance(target, ast.Attribute):
                names.append(target.attr)
    return names


@pytest.mark.parametrize("path,name", _BINDERS, ids=[b[1] for b in _BINDERS])
def test_override_binder_finalizes_the_layer(path, name):
    assert _FINALIZER in _calls(_function(path, name)), (
        f"{name} binds channel overrides under halt_update but never calls "
        f"{_FINALIZER}; the layer would have no Mapping node"
    )


@pytest.mark.parametrize("path,name", _BINDERS, ids=[b[1] for b in _BINDERS])
def test_finalize_runs_after_halt_update_is_restored(path, name):
    """Calling it inside the halted block would be a no-op for the callbacks."""
    func = _function(path, name)
    tries = [n for n in ast.walk(func) if isinstance(n, ast.Try)]
    assert tries, f"{name} no longer guards the bind with try/finally"
    inside = {
        node.func.id
        for handler in tries
        for node in ast.walk(handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert _FINALIZER not in inside, (
        f"{name} calls {_FINALIZER} inside the halt_update block, where the "
        "property callbacks it depends on are still suppressed"
    )


def test_finalizer_creates_the_mapping_and_rewires_the_tree():
    """The helper must run the node check, not just reconnect."""
    func = _function(
        "src/scripts/mixar/modules/paint/core/node/check_layer_io_nodes.py",
        _FINALIZER,
    )
    called = _calls(func)
    for required in (
        "check_all_layer_channel_io_and_nodes",  # creates the Mapping node
        "check_uv_nodes",
        "reconnect_layer_nodes",
        "rearrange_layer_nodes",
        "reconnect_mp_nodes",
        "rearrange_mp_nodes",
    ):
        assert required in called, f"{_FINALIZER} no longer calls {required}"


def test_mapping_node_creation_still_keys_on_is_layer_using_vector():
    """The check's mapping branch is what the binders rely on."""
    source = (
        _REPO
        / "src/scripts/mixar/modules/paint/core/node/check_layer_io_nodes.py"
    ).read_text(encoding="utf-8")
    assert "is_layer_using_vector(layer)" in source
    assert '"ShaderNodeMapping"' in source
