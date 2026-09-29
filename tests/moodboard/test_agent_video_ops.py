# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The agent's video operators: ``mixie.agent_video_generate`` / ``_upscale``.

The backend agent's ``enqueue_generation`` tool calls these with explicit
kwargs (never the tab's UI state): moodboard media by NAME, the model's
catalog params as ONE JSON string, and a refusal reason read back through
``mixar_agent_gen_reason``. Pins the bpy-free decisions in
``core/agent_video.py`` directly, drives both operators end to end with the
catalog, media description and enqueue seams stubbed, and pins the
registration + the two ``bl_idname`` strings the backend's GENERATION_SPECS
freeze.
"""

import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "src" / "scripts"
OPERATORS = SCRIPTS / "mixar" / "modules" / "moodboard" / "ui" / "operators"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

# The enqueue helper imports the job_queue package, whose API client pulls in
# the auth module; the standalone suite intentionally does not install the
# platform keyring dependency (same stub as test_video_upscale_wiring.py).
if "keyring" not in sys.modules:
    sys.modules["keyring"] = ModuleType("keyring")

from mixar.modules.moodboard.core import agent_video
from mixar.modules.moodboard.ui.operators import (
    agent_video_gen_ops,
    agent_video_upscale_ops,
)

#: Frozen with the backend (modules/agent/tools/domains/generation.py).
VIDEO_GEN_BL_IDNAME = "mixie.agent_video_generate"
VIDEO_UPSCALE_BL_IDNAME = "mixie.agent_video_upscale"

SEEDANCE = {
    "slug": "seedance-2-5", "is_default": True,
    "parameters": {
        "duration": {"type": "integer", "default": 5, "min": 4, "max": 30},
        "resolution": {"type": "string", "default": "720p", "enum": ["480p", "720p"]},
        "generate_audio": {"type": "boolean", "default": True},
        "image_mode": {"type": "string", "default": "reference"},
        "_reference_limits": {"max_images": 30},
    },
}
H3 = {
    "slug": "minimax-h3", "is_default": False,
    "parameters": {"duration": {"type": "integer", "default": 5, "min": 5, "max": 15}},
    "reference_limits": {"max_images": 9, "max_videos": 3, "max_materials": 12,
                         "max_video_seconds": 15},
}
UPSCALE = {
    "slug": "flux-video-upscale", "is_default": True,
    "parameters": {
        "upscale_factor": {"type": "float", "default": 2.0},
        "creativity": {"type": "string", "default": "precise", "enum": ["precise", "creative"]},
    },
}
VIDEO_GEN_SERVICE = {
    "key": "video_gen",
    "models": [SEEDANCE, H3],
    "input_spec": {
        "inputs": [
            {"name": "prompt", "kind": "prompt"},
            {"name": "reference_images", "kind": "image", "multiple": True, "max_count": 30,
             "max_size_mb": 30},
            {"name": "reference_videos", "kind": "video", "multiple": True, "max_count": 10,
             "max_total_duration_seconds": 30.2, "max_size_mb": 150,
             "extensions": [".mp4", ".mov", ".m4v"]},
        ],
        "max_materials": 50,
    },
}
UPSCALE_SERVICE = {"key": "video_upscale", "models": [UPSCALE]}
SERVICES = {"video_gen": VIDEO_GEN_SERVICE, "video_upscale": UPSCALE_SERVICE}


# ── the bpy-free decisions ──────────────────────────────────────────────


def _item(name):
    return SimpleNamespace(image=SimpleNamespace(name=name))


def _describe(item):
    name = item.image.name
    return {
        "image": item.image, "image_name": name,
        "media_type": "VIDEO" if name in ("gone",) or name.startswith("Street") else "IMAGE",
        "filename": f"{name}.mp4", "mime_type": "video/mp4",
        "resolved_filepath": f"/videos/{name}.mp4", "file_size_bytes": 1024,
        "source_available": name != "gone",
    }


def test_names_split_on_commas_and_keep_order_without_repeats():
    assert agent_video.split_names(" a, b ,a,,c ") == ["a", "b", "c"]
    assert agent_video.split_names("") == [] and agent_video.split_names(None) == []


def test_media_resolves_by_datablock_name_in_the_order_given():
    scene = SimpleNamespace(mixie_moodboard_images=[_item("mood_2"), _item("Street_Dolly"),
                                                    _item("mood_1"), SimpleNamespace(image=None)])
    stills = agent_video.find_moodboard_media(
        scene, ["mood_1", "mood_2"], describe=_describe, want_video=False)
    assert [m["image_name"] for m in stills] == ["mood_1", "mood_2"]
    movies = agent_video.find_moodboard_media(
        scene, ["Street_Dolly"], describe=_describe, want_video=True)
    assert movies[0]["media_type"] == "VIDEO"


@pytest.mark.parametrize("names,want_video,reason", [
    (["nope"], False, "No moodboard media named 'nope'"),
    (["Street_Dolly"], False, "is a video on the moodboard, not a image"),
    (["mood_1"], True, "is an image on the moodboard, not a video"),
    (["gone"], True, "was moved or deleted"),
])
def test_a_wrong_name_or_kind_is_a_reason_the_agent_can_act_on(names, want_video, reason):
    scene = SimpleNamespace(mixie_moodboard_images=[_item("Street_Dolly"), _item("mood_1"),
                                                    _item("gone")])
    with pytest.raises(ValueError, match=reason):
        agent_video.find_moodboard_media(scene, names, describe=_describe, want_video=want_video)


def test_params_are_the_models_defaults_under_the_agents_values():
    merged = agent_video.merge_catalog_params(SEEDANCE, json.dumps({"duration": 8}))
    assert merged == {"duration": 8, "resolution": "720p", "generate_audio": True,
                      "image_mode": "reference"}
    # Row metadata is never a parameter; an unknown key is the two sides
    # disagreeing on the model, not something to forward.
    with pytest.raises(ValueError, match="Unknown parameter.*prompt_expansion_mode"):
        agent_video.merge_catalog_params(SEEDANCE, '{"prompt_expansion_mode": "quality"}')
    with pytest.raises(ValueError, match="JSON object"):
        agent_video.merge_catalog_params(SEEDANCE, "[1, 2]")
    with pytest.raises(ValueError, match="not a JSON object"):
        agent_video.merge_catalog_params(SEEDANCE, "{oops")
    # No catalog row (not loaded yet): pass through, the server validates.
    assert agent_video.merge_catalog_params(None, '{"duration": 8}') == {"duration": 8}
    assert agent_video.merge_catalog_params(SEEDANCE, "") == {
        "duration": 5, "resolution": "720p", "generate_audio": True, "image_mode": "reference"}


def test_a_requested_model_is_never_silently_swapped_for_the_default():
    get_model = lambda service, slug: {"seedance-2-5": SEEDANCE, "minimax-h3": H3}.get(slug)
    get_default = lambda service: "seedance-2-5"
    resolve = agent_video.resolve_agent_model
    assert resolve("video_gen", "", get_model=get_model, get_default=get_default) == "seedance-2-5"
    assert resolve("video_gen", " minimax-h3 ", get_model=get_model,
                   get_default=get_default) == "minimax-h3"
    with pytest.raises(ValueError, match="'kling' is not an enabled video_gen model"):
        resolve("video_gen", "kling", get_model=get_model, get_default=get_default)
    with pytest.raises(ValueError, match="No enabled video_gen model"):
        resolve("video_gen", "", get_model=get_model, get_default=lambda s: None)


# ── the operators, end to end ───────────────────────────────────────────


@pytest.fixture
def seams(monkeypatch):
    """Stub the catalog, media description, compression and enqueue; collect
    the refusal reasons and the enqueue calls."""
    from mixar.bootstrap import generation_catalog_cache as cache
    from mixar.modules.common import job_queue
    from mixar.modules.common.utils import agent_feedback
    from mixar.modules.moodboard.core import media_utils, video_upscale_enqueue

    calls = SimpleNamespace(enqueued=[], upscaled=[], reasons=[], prepared=[])

    monkeypatch.setattr(cache, "get_service", lambda key: SERVICES.get(key))
    monkeypatch.setattr(cache, "get_model", lambda key, slug: next(
        (m for m in SERVICES.get(key, {}).get("models", []) if m["slug"] == slug), None))
    monkeypatch.setattr(cache, "get_default_model_slug", lambda key: next(
        (m["slug"] for m in SERVICES.get(key, {}).get("models", []) if m["is_default"]), None))
    monkeypatch.setattr(media_utils, "describe_moodboard_media", _describe)
    monkeypatch.setattr(agent_feedback, "set_agent_gen_reason",
                        lambda context, reason: calls.reasons.append(reason))
    monkeypatch.setattr(agent_feedback, "clear_agent_gen_reason", lambda context: None)

    image_utils = ModuleType("mixar.modules.common.utils.image_utils")
    image_utils.compress_for_service = lambda image, service: b"jpeg:" + image.name.encode()
    monkeypatch.setitem(sys.modules, "mixar.modules.common.utils.image_utils", image_utils)

    def _enqueue(**kwargs):
        calls.enqueued.append(kwargs)
        return object()

    monkeypatch.setattr(job_queue, "enqueue_generation", _enqueue)

    def _prepare(videos, limits=None):
        calls.prepared.append(videos)
        return ({"filename": videos[0]["filename"], "filepath": videos[0]["resolved_filepath"]},
                {"max_seconds": 20.0, "upload_purpose": "video_upscale"})

    def _upscale(**kwargs):
        calls.upscaled.append(kwargs)
        return object()

    monkeypatch.setattr(video_upscale_enqueue, "prepare_video_upscale_source", _prepare)
    monkeypatch.setattr(video_upscale_enqueue, "enqueue_video_upscale", _upscale)
    return calls


def _context(*names):
    return SimpleNamespace(
        scene=SimpleNamespace(mixie_moodboard_images=[_item(n) for n in names]),
        window_manager=MagicMock(),
    )


def _video_gen(**props):
    op = agent_video_gen_ops.MIXIE_OT_agent_video_generate()
    op.report = lambda *args, **kwargs: None
    defaults = {"prompt": "", "model": "", "reference_image_names": "",
                "reference_video_names": "", "params": ""}
    for name, value in {**defaults, **props}.items():
        setattr(op, name, value)
    return op


def _upscale_op(**props):
    op = agent_video_upscale_ops.MIXIE_OT_agent_video_upscale()
    op.report = lambda *args, **kwargs: None
    defaults = {"video_name": "", "prompt": "", "model": "", "params": ""}
    for name, value in {**defaults, **props}.items():
        setattr(op, name, value)
    return op


def test_video_generate_enqueues_the_named_references_through_the_tab_path(seams):
    op = _video_gen(prompt="keep the camera path of @Video1, rainy night",
                    reference_video_names="Street_Dolly",
                    reference_image_names="mood_1, mood_2",
                    params=json.dumps({"duration": 8}))
    assert op.execute(_context("mood_2", "Street_Dolly", "mood_1")) == {'FINISHED'}
    assert seams.reasons == []
    (call,) = seams.enqueued
    assert call["kind"] == "video" and call["feature_key"] == "video_gen"
    assert call["job_type"] == "video_gen" and call["model"] == "seedance-2-5"
    assert call["payload"] == {
        "prompt": "keep the camera path of @Video1, rainy night",
        "params": {"duration": 8, "resolution": "720p", "generate_audio": True,
                   "image_mode": "reference"},
    }
    assert [v["filename"] for v in call["video_inputs"]] == ["Street_Dolly.mp4"]
    assert [i["bytes"] for i in call["image_inputs"]] == [b"jpeg:mood_1", b"jpeg:mood_2"]
    assert call["max_video_duration_seconds"] == 30.2
    assert call["scene_flag"] == "mixie_video_gen_is_generating"
    assert call["origin_capability_key"] == "video_gen"


def test_video_generate_narrows_the_limits_to_the_chosen_model(seams):
    # Ten stills are fine for Seedance and one too many for H3: the refusal
    # is model-aware and lands BEFORE anything is compressed or uploaded.
    names = [f"mood_{i}" for i in range(10)]
    op = _video_gen(prompt="x", model="minimax-h3", reference_image_names=", ".join(names))
    assert op.execute(_context(*names)) == {'CANCELLED'}
    assert seams.reasons == ["Select at most 9 images"] and seams.enqueued == []


@pytest.mark.parametrize("props,reason", [
    ({}, "prompt is required"),
    ({"prompt": "x", "model": "kling"}, "'kling' is not an enabled video_gen model"),
    ({"prompt": "x", "reference_video_names": "nope"}, "No moodboard media named 'nope'"),
    ({"prompt": "x", "reference_image_names": "Street_Dolly"}, "is a video on the moodboard"),
    ({"prompt": "x", "params": '{"seed_of_doom": 1}'}, "Unknown parameter"),
    ({"prompt": "x", "params": '{"image_mode": "first_frame"}'}, "uses one image"),
])
def test_video_generate_refuses_with_a_reason_before_enqueueing(seams, props, reason):
    op = _video_gen(**props)
    assert op.execute(_context("Street_Dolly", "mood_1")) == {'CANCELLED'}
    assert len(seams.reasons) == 1 and reason in seams.reasons[0]
    assert seams.enqueued == []


def test_video_generate_reports_a_duplicate_and_an_enqueue_failure(seams, monkeypatch):
    from mixar.modules.common import job_queue

    monkeypatch.setattr(job_queue, "enqueue_generation", lambda **kwargs: None)
    assert _video_gen(prompt="x").execute(_context()) == {'CANCELLED'}
    assert seams.reasons[-1] == "A duplicate video generation is already queued"

    def _boom(**kwargs):
        raise RuntimeError("queue closed")

    monkeypatch.setattr(job_queue, "enqueue_generation", _boom)
    assert _video_gen(prompt="x").execute(_context()) == {'CANCELLED'}
    assert seams.reasons[-1] == "Failed to start video generation: queue closed"


def test_video_upscale_enqueues_the_named_movie_through_the_shared_path(seams):
    op = _upscale_op(video_name="Street_Dolly", prompt="sharper",
                     params=json.dumps({"creativity": "creative"}))
    assert op.execute(_context("Street_Dolly", "mood_1")) == {'FINISHED'}
    assert seams.reasons == []
    assert [v["image_name"] for v in seams.prepared[0]] == ["Street_Dolly"]
    (call,) = seams.upscaled
    assert call["service_key"] == "video_upscale" and call["model"] == "flux-video-upscale"
    assert call["prompt"] == "sharper"
    assert call["params"] == {"upscale_factor": 2.0, "creativity": "creative"}
    assert call["video_input"]["filepath"] == "/videos/Street_Dolly.mp4"
    assert call["limits"]["upload_purpose"] == "video_upscale"
    assert call["scene_flag"] == "mixie_video_upscale_is_generating"


@pytest.mark.parametrize("props,reason", [
    ({}, "video_name is required"),
    ({"video_name": "mood_1"}, "is an image on the moodboard, not a video"),
    ({"video_name": "nope"}, "No moodboard media named 'nope'"),
    ({"video_name": "Street_Dolly", "model": "topaz"}, "'topaz' is not an enabled video_upscale model"),
    ({"video_name": "Street_Dolly", "params": '{"factor": 2}'}, "Unknown parameter"),
])
def test_video_upscale_refuses_with_a_reason_before_enqueueing(seams, props, reason):
    assert _upscale_op(**props).execute(_context("Street_Dolly", "mood_1")) == {'CANCELLED'}
    assert len(seams.reasons) == 1 and reason in seams.reasons[0]
    assert seams.upscaled == []


def test_video_upscale_surfaces_the_source_check_and_a_duplicate(seams, monkeypatch):
    from mixar.modules.moodboard.core import video_upscale_enqueue

    def _too_long(videos, limits=None):
        raise ValueError("Video is longer than 20 seconds")

    monkeypatch.setattr(video_upscale_enqueue, "prepare_video_upscale_source", _too_long)
    assert _upscale_op(video_name="Street_Dolly").execute(_context("Street_Dolly")) == {'CANCELLED'}
    assert seams.reasons[-1] == "Video is longer than 20 seconds"

    monkeypatch.setattr(video_upscale_enqueue, "prepare_video_upscale_source",
                        lambda videos, limits=None: ({"filename": "x"}, {"max_seconds": 20.0}))
    monkeypatch.setattr(video_upscale_enqueue, "enqueue_video_upscale", lambda **kw: None)
    assert _upscale_op(video_name="Street_Dolly").execute(_context("Street_Dolly")) == {'CANCELLED'}
    assert seams.reasons[-1] == "A duplicate video upscale is already queued"


# ── registration + the frozen contract ──────────────────────────────────


def test_operators_carry_the_bl_idnames_the_backend_specs_freeze():
    assert agent_video_gen_ops.MIXIE_OT_agent_video_generate.bl_idname == VIDEO_GEN_BL_IDNAME
    assert agent_video_upscale_ops.MIXIE_OT_agent_video_upscale.bl_idname == VIDEO_UPSCALE_BL_IDNAME


def test_both_operator_modules_are_registered():
    # agent_auto_rig_ops shipped once without this line and every enqueue
    # failed with "operator not found"; pin it for the video pair.
    source = (OPERATORS / "__init__.py").read_text(encoding="utf-8")
    modules_block = source[source.index("modules = ("):]
    assert "agent_video_gen_ops," in modules_block
    assert "agent_video_upscale_ops," in modules_block
