# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Every generate path must resolve a multi-view set FROM the image.

A multi-view set is bound to exactly one image — its frontal (main) image,
marked with ``turnaround_main_group``. Resolving the set from the TAB instead
(``get_active_group``) was a production defect: turn 1 detected a turnaround
sheet for one subject, turn 2 converted an unrelated image, and that image
inherited the earlier subject's companion views and generated as a morph of
the two. The refusal the guard raised also pushed the agent into retrying and
then switching to the one multi-view engine it knew, which is how the wrong
views got submitted at all.

``build_active_group_payload`` is the single place the binding, the model
capability check and the terminal error wording live. These tests pin every
operator to it, because the operators themselves cannot be exercised outside
Blender: ``bpy.types.Operator`` is a ``MagicMock``, so
``class MIXIE_OT_x(Operator)`` produces a mock rather than a class and its
methods are unreachable. A source-level assertion is drift-proof in a way a
hand-copied replay of the method body would not be.
"""

import ast
from pathlib import Path

import pytest

from mixar.modules.moodboard.core.turnaround_views import (
    build_active_group_payload,
)
# The board fakes are shared with the group-model tests rather than copied:
# tests/moodboard has no __init__.py, so pytest's prepend import mode puts the
# directory on sys.path and this resolves.
from test_turnaround_views import FakeTab, _main, _scene

_OPERATORS = Path(__file__).resolve().parents[2] / (
    "src/scripts/mixar/modules/moodboard/ui/operators")

# Both generate paths onto the Model Gen tab: the catalog-driven operator that
# is live today (mixie.model_gen_generate), and the pre-catalog fallback that
# the agent also invokes directly (mixie.image_to_3d_generate).
_GENERATE_OPS = ("model_gen_ops.py", "image_to_3d_ops.py")


def _turnaround_method(filename):
    """The `_turnaround_payload` FunctionDef node from *filename*."""
    tree = ast.parse((_OPERATORS / filename).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and \
                node.name == "_turnaround_payload":
            return node
    raise AssertionError(f"{filename} has no _turnaround_payload")


def _names(node):
    """Every identifier referenced inside *node*."""
    found = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            found.add(child.id)
        elif isinstance(child, ast.Attribute):
            found.add(child.attr)
        elif isinstance(child, ast.alias):
            found.add(child.asname or child.name)
    return found


@pytest.mark.parametrize("filename", _GENERATE_OPS)
def test_generate_paths_resolve_the_set_from_the_image_not_the_tab(filename):
    names = _names(_turnaround_method(filename))

    assert "build_active_group_payload" in names, (
        f"{filename} must resolve the multi-view set through "
        "build_active_group_payload, which binds it to the image being "
        "converted"
    )
    assert "get_active_group" not in names, (
        f"{filename} reads the set off the TAB. That is the production "
        "defect: an unrelated Input Image inherits a set left over from an "
        "earlier subject"
    )
    assert "build_multi_view_payload" not in names, (
        f"{filename} calls build_multi_view_payload directly, bypassing the "
        "binding and the capability check"
    )


def test_model_gen_does_not_pre_gate_on_multi_view_support():
    """An incapable model on a bound main must cancel loudly.

    ``model_supports_multi_view`` as an early-out would return None for
    'tripo-low' and silently drop the set — exactly the degrade-to-one-image
    that build_active_group_payload's terminal ValueError exists to prevent.
    The operator still computes supports_mv for its input validation; it just
    must not gate the turnaround path on it.
    """
    node = _turnaround_method("model_gen_ops.py")
    names = _names(node)

    assert "supports_mv" not in names
    assert "model_supports_multi_view" not in names
    assert "supports_mv" not in {a.arg for a in node.args.args}


@pytest.mark.parametrize("filename", _GENERATE_OPS)
def test_generate_paths_keep_the_none_false_fragment_contract(filename):
    """``None`` = no set, ``False`` = cancel, else the payload fragment.

    ``execute`` distinguishes the three with ``is False`` / truthiness, so a
    path that stopped returning False on an unusable set would submit a
    single-image job the user did not ask for.
    """
    node = _turnaround_method(filename)
    returns = [
        child.value for child in ast.walk(node)
        if isinstance(child, ast.Return)
    ]
    literals = {
        child.value for child in returns
        if isinstance(child, ast.Constant)
    }

    assert None in literals, f"{filename} must return None when there is no set"
    assert False in literals, f"{filename} must return False to cancel"
    # And the ValueError is caught rather than escaping into execute().
    handlers = [
        child for child in ast.walk(node) if isinstance(child, ast.ExceptHandler)
    ]
    assert any(
        isinstance(h.type, ast.Name) and h.type.id == "ValueError"
        for h in handlers
    ), f"{filename} must catch the terminal ValueError and report it"


# ---------------------------------------------------------------------------
# What the Model Gen tab actually submits
#
# Its service key comes from resolve_service_key("model_gen", tab.mode) — so
# Pro mode asks about 'image_to_3d', NOT 'model_3d'. The key is threaded from
# execute() rather than hardcoded, and these exercise that.
# ---------------------------------------------------------------------------

@pytest.fixture
def pro_accepts_mv(monkeypatch):
    """Only Pro mode's engine takes multi-view input."""
    monkeypatch.setattr(
        "mixar.modules.moodboard.core.turnaround_views."
        "model_accepts_multi_view",
        lambda service, model: (
            service == "image_to_3d" and model == "hunyuan-pro-fal"
        ),
    )


def _ganesha_board():
    """Turn 1's detected turnaround, plus turn 2's unrelated dragon image."""
    tab = FakeTab(group="turnaround_47427eba181e")
    scene = _scene(
        ("ganesha_left", "left", "k/left.png"),
        ("ganesha_back", "back", "k/back.png"),
        group="turnaround_47427eba181e",
        tab=tab,
    )
    _main("ganesha_main", "k/ganesha.png", scene,
          main_of="turnaround_47427eba181e")
    dragon = _main("dragon_front_001", "k/dragon.png", scene)
    return scene, dragon


def test_model_gen_does_not_attach_a_stale_set_to_an_unrelated_image(
    pro_accepts_mv,
):
    """The named production regression, on the live sidebar path.

    'hunyuan-pro-fal' IS multi-view capable, so the old supports_mv pre-gate
    let this straight through: the dragon inherited Ganesha's left/back views
    and generated as a morph of the two.
    """
    scene, dragon = _ganesha_board()

    assert build_active_group_payload(
        scene, dragon, "image_to_3d", "hunyuan-pro-fal") is None


def test_model_gen_still_submits_the_set_from_its_own_main(pro_accepts_mv):
    scene, _dragon = _ganesha_board()
    ganesha = next(
        i.image for i in scene.mixie_moodboard_images
        if i.image.name == "ganesha_main"
    )

    payload, warnings = build_active_group_payload(
        scene, ganesha, "image_to_3d", "hunyuan-pro-fal")

    assert payload == {
        "image_s3_key": "k/ganesha.png",
        "multi_view_images": [
            {"s3_key": "k/left.png", "view_type": "left"},
            {"s3_key": "k/back.png", "view_type": "back"},
        ],
    }
    assert warnings == []


def test_model_gen_capability_is_checked_against_its_own_service(
    pro_accepts_mv,
):
    """Threading service_key matters: the Model Gen tab's Pro mode is
    'image_to_3d', so a hardcoded 'model_3d' would ask about the wrong
    service and wrongly refuse a set the selected engine can take."""
    scene, _dragon = _ganesha_board()
    ganesha = next(
        i.image for i in scene.mixie_moodboard_images
        if i.image.name == "ganesha_main"
    )

    # Same engine, wrong service key -> refused. This is what hardcoding did.
    with pytest.raises(ValueError, match="do NOT retry with a different model"):
        build_active_group_payload(
            scene, ganesha, "model_3d", "hunyuan-pro-fal")


def test_model_gen_refuses_an_incapable_model_on_a_bound_main(pro_accepts_mv):
    """No silent degrade — the pre-gate used to drop the set here."""
    scene, _dragon = _ganesha_board()
    ganesha = next(
        i.image for i in scene.mixie_moodboard_images
        if i.image.name == "ganesha_main"
    )

    with pytest.raises(ValueError) as excinfo:
        build_active_group_payload(
            scene, ganesha, "image_to_3d", "tripo-low")

    assert "'tripo-low' cannot use the 2-view set on 'ganesha_main'" \
        in str(excinfo.value)


# ---------------------------------------------------------------------------
# Detect ingest must not hold a CollectionProperty item across further adds
# ---------------------------------------------------------------------------

_DETECT = Path(__file__).resolve().parents[2] / (
    "src/scripts/mixar/modules/moodboard/core/turnaround_detect.py")


def _ingest_function():
    """The `_add_panels_to_moodboard` FunctionDef node."""
    tree = ast.parse(_DETECT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and \
                node.name == "_add_panels_to_moodboard":
            return node
    raise AssertionError("turnaround_detect has no _add_panels_to_moodboard")


def test_ingest_binds_the_main_by_image_not_by_a_held_item():
    """The main crop's binding must survive the rest of the ingest loop.

    Production (uat2, twice): a 7-panel Ganesha sheet ingested fine — crops
    placed, companions grouped, S3 keys set — yet its main image came out with
    an empty ``turnaround_main_group``, so the set never attached and only the
    main image reached the API. A 4-panel Frog King sheet in the same session
    bound correctly.

    ``_place`` returns ``scene.mixie_moodboard_images[-1]``, a live reference
    into a Blender CollectionProperty. The main crop is ``panels[0]``, so
    holding its item and writing the marker AFTER the loop meant writing
    through a pointer that six subsequent adds may have invalidated. Every
    other write in the loop (``s3_key``, ``view_type``, ``turnaround_group``)
    happens immediately after its own ``_place`` and survived — exactly what
    the scene dump showed.

    The binding must therefore be resolved from the main IMAGE (an ID
    datablock, stable across collection mutations) after the loop.
    """
    node = _ingest_function()
    names = _names(node)

    assert "set_group_main_image" in names, (
        "_add_panels_to_moodboard must bind the set via set_group_main_image, "
        "which re-resolves the item from the image datablock"
    )

    assigned = {
        target.id
        for child in ast.walk(node)
        if isinstance(child, ast.Assign)
        for target in child.targets
        if isinstance(target, ast.Name)
    }
    assert "main_item" not in assigned, (
        "_add_panels_to_moodboard captures a moodboard item for the main crop "
        "and writes to it after further _place() calls. That reference can be "
        "invalidated by the adds in between, silently dropping the binding"
    )

    assert not any(
        isinstance(child, ast.Attribute)
        and child.attr == "turnaround_main_group"
        and isinstance(child.ctx, ast.Store)
        for child in ast.walk(node)
    ), (
        "_add_panels_to_moodboard writes turnaround_main_group directly; go "
        "through set_group_main_image so the one-main-per-group invariant and "
        "the by-image resolution are enforced in one place"
    )
