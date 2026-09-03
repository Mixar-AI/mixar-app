# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Model slugs are catalog data — never client literals.

Which model rows exist under a service is server state that changes without a
client release. A remembered slug therefore does not fail loudly; it spends a
queue slot and the user's wait on a 422, or (worse) submits a *different*
engine than the one the constant was named after. These tests pin the submit
paths to the catalog and pin the catalog-absent behaviour to "refuse", not
"guess a default".

Source-level (``ast``) assertions are used where a runtime one is impossible:
outside Blender ``bpy.types.Operator`` is a ``MagicMock``, so operator classes
never really exist — see ``test_turnaround_operator_wiring`` for the same
technique and the reasoning behind it.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ``scene_gen_queue`` transitively imports the API client -> auth, and auth's
# darwin/linux branch imports the optional ``keyring`` package, which is only
# present inside a Blender build. Stub it for the same reason (and in the same
# way) the root conftest stubs ``bpy``: the code under test here never touches
# a credential store.
for _name in ("keyring", "keyring.errors"):
    sys.modules.setdefault(_name, MagicMock(name=_name))

_SRC = Path(__file__).resolve().parents[2] / "src/scripts/mixar"
_MODULES = _SRC / "modules"


# ---------------------------------------------------------------------------
# catalog_default_model — the shared "no guessing" accessor
# ---------------------------------------------------------------------------

def test_catalog_default_model_returns_catalog_slug():
    from mixar.modules.common.generation_params import catalog_default_model

    with patch(
        "mixar.bootstrap.generation_catalog_cache.get_default_model_slug",
        return_value="scene_gen_v1",
    ):
        assert catalog_default_model("scene_gen") == "scene_gen_v1"


def test_catalog_default_model_returns_none_when_catalog_absent():
    """No catalog means unknown, and unknown must not become a literal."""
    from mixar.modules.common.generation_params import catalog_default_model

    with patch(
        "mixar.bootstrap.generation_catalog_cache.get_default_model_slug",
        return_value=None,
    ):
        assert catalog_default_model("scene_gen") is None


def test_catalog_default_model_rejects_placeholder_ids():
    """LOADING/ERROR/NONE are enum placeholders, not submittable slugs."""
    from mixar.modules.common.generation_params import catalog_default_model

    for placeholder in ("LOADING", "ERROR", "NONE", ""):
        with patch(
            "mixar.bootstrap.generation_catalog_cache.get_default_model_slug",
            return_value=placeholder,
        ):
            assert catalog_default_model("scene_gen") is None


def test_catalog_default_model_survives_cache_import_failure():
    """Pre-bootstrap import errors must degrade to None, never raise."""
    from mixar.modules.common.generation_params import catalog_default_model

    with patch(
        "mixar.bootstrap.generation_catalog_cache.get_default_model_slug",
        side_effect=RuntimeError("cache not registered"),
    ):
        assert catalog_default_model("scene_gen") is None


# ---------------------------------------------------------------------------
# Scene Gen — was SCENE_GEN_MODEL = "scene_gen_v1"
# ---------------------------------------------------------------------------

def test_scene_gen_model_constant_is_gone():
    from mixar.modules.moodboard import constants

    assert not hasattr(constants, "SCENE_GEN_MODEL")


def test_scene_gen_submits_the_catalog_default():
    from mixar.modules.moodboard.core import scene_gen_queue

    with patch.object(
        scene_gen_queue, "get_queue_with_listener"
    ) as queue_factory, patch(
        "mixar.modules.common.generation_params.catalog_default_model",
        return_value="scene_gen_v9",
    ):
        queue_factory.return_value.submit.return_value = True
        job = scene_gen_queue.enqueue_scene_gen_job(
            label="sheet.png", payload={"image_bytes_b64": "x"})

    assert job is not None
    assert job.model == "scene_gen_v9"


def test_scene_gen_refuses_to_submit_without_a_catalog():
    """Fail closed: no catalog, no submit — do not fall back to a literal."""
    from mixar.modules.moodboard.core import scene_gen_queue

    with patch.object(
        scene_gen_queue, "get_queue_with_listener"
    ) as queue_factory, patch(
        "mixar.modules.common.generation_params.catalog_default_model",
        return_value=None,
    ):
        job = scene_gen_queue.enqueue_scene_gen_job(
            label="sheet.png", payload={"image_bytes_b64": "x"})

    assert job is None
    queue_factory.assert_not_called()


# ---------------------------------------------------------------------------
# Scene Gen LP retopology — was model="hunyuan_topology"
# ---------------------------------------------------------------------------

def test_scene_gen_lp_pins_hunyuan_topology_deliberately():
    """LP is NOT catalog-defaulted, and that is the intended behaviour.

    `shared_params` carries polygon_type / face_level / post_process — Hunyuan
    Topology's knobs. Resolving the `retopology` service default instead would
    hand those to whichever engine is default, silently swapping engines and
    failing submit validation if that engine's schema lacks them. Reviewed and
    reverted on purpose, so this pins it rather than leaving it looking like an
    oversight the next cleanup should "fix".
    """
    from mixar.modules.hunyuan.constants import RETOPOLOGY_HUNYUAN_MODEL

    source = (_MODULES / "moodboard/core/generation_enqueue.py").read_text(encoding="utf-8")
    assert "RETOPOLOGY_HUNYUAN_MODEL" in source
    assert "catalog_default_model" not in source, (
        "Scene Gen LP must not resolve its engine from the catalog default"
    )
    # The named constant, not a literal, is what the call site uses.
    assert '"hunyuan_topology"' not in source
    assert RETOPOLOGY_HUNYUAN_MODEL == "hunyuan_topology"


# ---------------------------------------------------------------------------
# Gemini model ids: a second vocabulary for catalog-served models
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", [
    "GEMINI_MODELS",
    "MOODBOARD_GEMINI_MODEL_DEFAULT",
])
def test_raw_vendor_model_ids_are_gone(name):
    from mixar.modules.moodboard import constants

    assert not hasattr(constants, name)


# ---------------------------------------------------------------------------
# Deliberately KEPT — these guard behaviour, not convenience
# ---------------------------------------------------------------------------

def test_registration_time_enums_stay_static():
    """A dynamic EnumProperty ``items=`` callback remaps or loses the values
    stored in saved .blend files. These must NOT be made catalog-driven."""
    from mixar.modules.moodboard import constants

    assert len(constants.TURNAROUND_VIEW_TYPES) == 7
    assert constants.TURNAROUND_MAX_COMPANIONS == 7
    assert [r[0] for r in constants.ASPECT_RATIOS][:2] == ['1:1', '16:9']


def test_no_client_side_angle_gating_by_slug():
    """Angle capability is catalog data; the client must not guess it.

    This was keyed on a hardcoded slug list ("Hunyuan 3.0 takes left/right/back
    only"). Those slugs name rows that are disabled in the catalog, so the gate
    never fired — it was dead code that still encoded a vendor-version
    assumption on the client. Narrowing belongs in the model's ``parameters``
    schema (a ``view_type`` enum), which ``allowed_view_types`` is the seam for.
    """
    from mixar.modules.moodboard import constants
    from mixar.modules.moodboard.core.turnaround_views import (
        allowed_view_types,
    )

    assert not hasattr(constants, "TURNAROUND_BASE_ANGLE_ONLY_SLUGS")
    assert not hasattr(constants, "TURNAROUND_VIEW_TYPES_V30")
    for slug in ("hunyuan_pro_v3", "hunyuan_pro_v3.1", "hunyuan-pro-fal", ""):
        assert allowed_view_types(slug) == constants.TURNAROUND_VIEW_ORDER


def test_pr_adds_no_new_hardcoded_vendor_version_slugs():
    """Nothing this PR touches may introduce a version->slug literal.

    The two that existed (moodboard/constants.py's slug list and a copy of the
    ternary in hunyuan_ops) were the whole point of the de-hardcoding review.
    The pre-existing pair in generation_enqueue is develop's and is left alone.
    """
    offenders = sorted(
        path.relative_to(_MODULES).as_posix()
        for path in _MODULES.rglob("*.py")
        if "__pycache__" not in path.parts
        and "hunyuan_pro_v3.1" in path.read_text(encoding="utf-8")
    )
    assert offenders == ["moodboard/core/generation_enqueue.py"], offenders
