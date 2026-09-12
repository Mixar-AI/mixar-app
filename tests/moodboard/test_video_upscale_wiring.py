# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Video Upscale (FLUX Video Upscale on fal): one source clip, one contract.

Pins the two submit surfaces (sidebar tab + canvas node) to ONE enqueue path,
the upload ``purpose`` that routes the source through the backend's upscale
validation, the single ``video_s3_key`` payload shape, and every registry
the feature must appear in (queue bucket, prompt dispatch, tab labels,
telemetry map, C++ output-kind table).
"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType, SimpleNamespace
import re
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / "src/scripts/mixar/modules"
MOODBOARD = MODULES / "moodboard"
SPACE_MIXIE = ROOT / "src/source/blender/editors/space_mixie"
CATALOG_MODULE = "mixar.bootstrap.generation_catalog_cache"

sys.path.insert(0, str(ROOT / "src/scripts"))

# The enqueue helper imports the job_queue package, whose API client pulls in
# the auth module; the standalone suite intentionally does not install the
# platform keyring dependency (same stub as tests/test_telemetry_expansion.py).
if "keyring" not in sys.modules:
    sys.modules["keyring"] = ModuleType("keyring")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_catalog_module():
    spec = spec_from_file_location(
        "video_upscale_catalog_under_test",
        MOODBOARD / "core/video_upscale_catalog.py",
    )
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _catalog_stub(service):
    module = ModuleType(CATALOG_MODULE)
    module.get_service = lambda _key: service
    return module


def _service(**video_overrides):
    video = {
        "name": "video",
        "kind": "video",
        "required": True,
        "multiple": False,
        "max_count": 1,
        "max_duration_seconds": 20,
        "max_size_mb": 50,
        "max_side_pixels": 2560,
        "max_pixels": 2560 * 1440,
        "extensions": [".MP4", ".mov", ".m4v"],
        "upload_purpose": "video_upscale",
    }
    video.update(video_overrides)
    return {
        "input_spec": {
            "inputs": [video, {"name": "prompt", "kind": "prompt", "required": False}],
            "max_materials": 1,
        }
    }


def _video(filename="clip.mp4", *, size=1024, available=True):
    return {
        "filename": filename,
        "mime_type": "video/mp4",
        "resolved_filepath": f"/tmp/{filename}",
        "file_size_bytes": size,
        "source_available": available,
    }


# --------------------------------------------------------------------------- #
# Catalog contract (standalone, no bpy)
# --------------------------------------------------------------------------- #


def test_limits_come_from_the_catalog_service(monkeypatch):
    monkeypatch.setitem(sys.modules, CATALOG_MODULE, _catalog_stub(_service()))
    limits = _load_catalog_module().get_video_upscale_limits("video_upscale")
    assert limits == {
        "max_seconds": 20.0,
        "max_bytes": 50 * 1024 * 1024,
        "max_side_pixels": 2560,
        "max_pixels": 2560 * 1440,
        "video_extensions": (".mp4", ".mov", ".m4v"),
        "upload_purpose": "video_upscale",
        "prompt_optional": True,
    }


def test_malformed_catalog_rows_fail_closed(monkeypatch):
    module = _load_catalog_module()
    for broken in (
        {},
        {"input_spec": {"inputs": []}},
        _service(max_duration_seconds=0),
        _service(extensions=[]),
        _service(max_size_mb="lots"),
        # A repeatable video input is a Video Gen shape, not an upscale source.
        _service(multiple=True),
    ):
        monkeypatch.setitem(sys.modules, CATALOG_MODULE, _catalog_stub(broken))
        assert module.get_video_upscale_limits("video_upscale") is None, broken


def test_optional_pixel_caps_are_tolerated(monkeypatch):
    service = _service()
    del service["input_spec"]["inputs"][0]["max_side_pixels"]
    del service["input_spec"]["inputs"][0]["max_pixels"]
    monkeypatch.setitem(sys.modules, CATALOG_MODULE, _catalog_stub(service))
    limits = _load_catalog_module().get_video_upscale_limits("video_upscale")
    assert limits["max_side_pixels"] is None and limits["max_pixels"] is None


def test_exactly_one_selected_video_is_required():
    module = _load_catalog_module()
    assert "Select one video" in module.video_upscale_source_error(None, video_count=0)
    assert "one video at a time" in module.video_upscale_source_error(None, video_count=2)
    assert module.video_upscale_source_error(None, video_count=1) is None


def test_source_validator_streams_from_the_path_and_checks_size_and_extension(monkeypatch):
    monkeypatch.setitem(sys.modules, CATALOG_MODULE, _catalog_stub(_service()))
    module = _load_catalog_module()
    limits = module.get_video_upscale_limits("video_upscale")

    shaped = module.build_video_upscale_input(_video(), limits)
    assert shaped == {
        "filename": "clip.mp4",
        "mime_type": "video/mp4",
        "filepath": "/tmp/clip.mp4",
        "file_size_bytes": 1024,
    }
    assert "bytes" not in shaped

    with pytest.raises(ValueError, match="too large"):
        module.build_video_upscale_input(_video(size=51 * 1024 * 1024), limits)
    with pytest.raises(ValueError, match="Unsupported video"):
        module.build_video_upscale_input(_video("clip.webm"), limits)
    with pytest.raises(ValueError, match="moved or deleted"):
        module.build_video_upscale_input(_video(available=False), limits)


def test_limit_hints_name_the_catalog_ceilings(monkeypatch):
    monkeypatch.setitem(sys.modules, CATALOG_MODULE, _catalog_stub(_service()))
    module = _load_catalog_module()
    lines = module.describe_source_limits(module.get_video_upscale_limits("video_upscale"))
    assert lines[0] == "Up to 20 seconds, 50 MB"
    assert "2560 px" in lines[1]
    assert lines[2] == "Formats: MP4, MOV, M4V"


# --------------------------------------------------------------------------- #
# The ONE enqueue path (bpy mocked by the root conftest)
# --------------------------------------------------------------------------- #


def test_enqueue_stages_the_source_under_the_upscale_purpose_as_a_single_key(monkeypatch):
    from mixar.modules.common import job_queue as job_queue_pkg
    from mixar.modules.moodboard.core import video_upscale_enqueue as enqueue

    captured = {}

    def fake_enqueue_generation(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id="job-1")

    monkeypatch.setattr(job_queue_pkg, "enqueue_generation", fake_enqueue_generation)
    limits = {"max_seconds": 20.0, "upload_purpose": "video_upscale"}
    video_input = {
        "filename": "walk.mov", "mime_type": "video/quicktime",
        "filepath": "/tmp/walk.mov", "file_size_bytes": 10,
    }

    job = enqueue.enqueue_video_upscale(
        service_key="video_upscale", model="flux-video-upscale",
        prompt="  crisp brick  ", params={"upscale_factor": 2.0, "creativity": "precise"},
        video_input=video_input, limits=limits, graph_node_id="abcdef0123",
        on_imported="hook",
    )

    assert job.id == "job-1"
    assert captured["kind"] == "video"
    assert captured["feature_key"] == "video_upscale"
    assert captured["job_type"] == "video_upscale"
    assert captured["origin_capability_key"] == "video_upscale"
    assert captured["payload"] == {
        "prompt": "crisp brick",
        "params": {"upscale_factor": 2.0, "creativity": "precise"},
    }
    assert captured["video_inputs"] == [video_input]
    assert not captured.get("image_inputs")
    assert captured["upload_purpose"] == "video_upscale"
    assert captured["video_key_field"] == "video_s3_key"
    assert captured["single_video_key"] is True
    assert captured["max_video_duration_seconds"] == 20.0
    assert captured["graph_node_id"] == "abcdef0123"
    assert captured["on_imported"] == "hook"
    assert captured["label"].startswith("VideoUpscale:abcdef01:")


def test_a_blank_prompt_is_omitted_from_the_payload(monkeypatch):
    from mixar.modules.common import job_queue as job_queue_pkg
    from mixar.modules.moodboard.core import video_upscale_enqueue as enqueue

    captured = {}
    monkeypatch.setattr(
        job_queue_pkg, "enqueue_generation",
        lambda **kwargs: captured.update(kwargs) or SimpleNamespace(id="j"),
    )
    enqueue.enqueue_video_upscale(
        service_key="video_upscale", model="flux-video-upscale", prompt="   ",
        params={}, video_input={"filename": "a.mp4"},
        limits={"max_seconds": 20.0, "upload_purpose": "video_upscale"},
    )
    assert "prompt" not in captured["payload"]
    assert captured["prompt_text"] == ""


def test_prepare_source_resolves_limits_and_refuses_a_second_clip(monkeypatch):
    from mixar.modules.moodboard.core import video_upscale_enqueue as enqueue

    limits = {
        "max_seconds": 20.0, "max_bytes": 50 * 1024 * 1024,
        "video_extensions": (".mp4",), "upload_purpose": "video_upscale",
    }
    shaped, resolved = enqueue.prepare_video_upscale_source([_video()], limits)
    assert shaped["filepath"] == "/tmp/clip.mp4" and resolved is limits
    with pytest.raises(ValueError, match="one video at a time"):
        enqueue.prepare_video_upscale_source([_video(), _video("b.mp4")], limits)
    with pytest.raises(ValueError, match="Select one video"):
        enqueue.prepare_video_upscale_source([], limits)


def test_streaming_job_lands_a_single_video_key_and_forwards_the_purpose():
    queue_job = _read(MODULES / "common/job_queue/core/generic_jobs.py")
    streaming = queue_job[queue_job.index("class StreamingVideoJob"):]
    assert 'upload_purpose: str = ""' in streaming
    assert 'video_key_field: str = "reference_video_s3_keys"' in streaming
    assert "single_video_key: bool = False" in streaming
    assert "self.payload[self.video_key_field]" in streaming
    assert "purpose=self.upload_purpose" in streaming
    assert "b64" not in streaming

    service = _read(MODULES / "common/api/services/job_queue_service.py")
    assert 'purpose: str = ""' in service
    assert "?purpose=" in service

    enqueue_src = _read(MODULES / "common/job_queue/core/enqueue.py")
    for kwarg in ("upload_purpose=upload_purpose", "video_key_field=video_key_field",
                  "single_video_key=single_video_key"):
        assert kwarg in enqueue_src


# --------------------------------------------------------------------------- #
# Both surfaces go through the shared path
# --------------------------------------------------------------------------- #


def test_sidebar_and_node_share_one_enqueue_and_one_validator():
    operator = _read(MOODBOARD / "ui/operators/video_upscale_ops.py")
    drawer = _read(MOODBOARD / "ui/video_upscale_drawer.py")
    runner = _read(MOODBOARD / "core/video_upscale_enqueue.py")
    execution = _read(MOODBOARD / "core/node_execution.py")

    assert "get_selected_moodboard_video_inputs(context, fresh=True)" in operator
    assert "fresh=True" not in drawer
    for name in ("resolve_video_upscale_target", "prepare_video_upscale_source",
                 "enqueue_video_upscale"):
        assert name in operator
    assert "enqueue_generation" not in operator
    assert "run_video_upscale_node" in runner and "run_video_upscale_node" in execution
    assert "elif node.action_type == 'VIDEO_UPSCALE':" in execution
    assert "build_video_upscale_input(videos[0], limits)" in runner
    assert "get_video_upscale_limits" in drawer
    assert "mixie.video_upscale_generate" in drawer
    assert 'mixie_video_upscale_is_generating' in drawer


# --------------------------------------------------------------------------- #
# Registries the feature must appear in
# --------------------------------------------------------------------------- #


def test_feature_is_registered_everywhere_a_capability_tab_needs():
    constants = _read(MODULES / "common/job_queue/constants.py")
    assert 'FEATURE_VIDEO_UPSCALE = "video_upscale"' in constants
    assert '"FEATURE_VIDEO_UPSCALE",' in constants

    queue_props = _read(MODULES / "common/job_queue/ui/properties/queue_properties.py")
    features = queue_props[queue_props.index("_FEATURES = ("):]
    assert "FEATURE_VIDEO_UPSCALE" in features[: features.index(")")]

    panels = _read(MOODBOARD / "ui/moodboard_sidebar_panels.py")
    assert '"video_upscale": (MIXIE_PT_gen_video_upscale, "Video Upscale")' in panels
    assert 'get_services("video_upscale")' in panels
    assert "MIXIE_PT_gen_video_upscale,\n" in panels[panels.index("classes = ("):]

    dispatch = _read(MOODBOARD / "core/prompt_submit.py")
    assert (
        '"MixieMoodboardTabVideoUpscaleProps": _static("mixie.video_upscale_generate")'
        in dispatch
    )

    registration = _read(MOODBOARD / "ui/moodboard_scene_registration.py")
    assert registration.count("MixieMoodboardTabVideoUpscaleProps") == 2
    assert "'mixie_video_upscale_is_generating'" in registration
    assert registration.count("'video_upscale'") == 2  # progress prefix: register + unregister

    tab_props = _read(MOODBOARD / "ui/moodboard_tab_properties.py")
    assert "tab_video_upscale: PointerProperty(" in tab_props

    telemetry = _read(MODULES / "common/analytics/draft_events.py")
    assert '"Video Upscale": "video_upscale"' in telemetry
    assert '"video_upscale": _snapshot_video_upscale' in telemetry


def test_node_type_is_appended_and_mirrored_in_cpp():
    from mixar.modules.moodboard.core.node_graph import _ACCEPTED_SOURCE_TYPES
    from mixar.modules.moodboard.core.node_schema import (
        _OUTPUT_TYPES,
        _capability_for_action,
        output_type_for_action,
    )
    from mixar.modules.moodboard.ui.moodboard_graph_properties import (
        ACTION_TYPES,
        capability_for_action,
    )

    # Append-only: the enum persists as an index.
    assert ACTION_TYPES[-1][0] == 'VIDEO_UPSCALE'
    assert _OUTPUT_TYPES['VIDEO_UPSCALE'] == 'VIDEO'
    assert output_type_for_action('VIDEO_UPSCALE') == 'VIDEO'
    assert _ACCEPTED_SOURCE_TYPES['VIDEO_UPSCALE'] == {'VIDEO'}
    # Two independent capability maps by design (import-cycle avoidance).
    assert capability_for_action('VIDEO_UPSCALE') == "video_upscale"
    assert _capability_for_action('VIDEO_UPSCALE') == "video_upscale"

    draw = _read(SPACE_MIXIE / "mixie_draw_moodboard_graph_sockets.cc")
    kinds = re.findall(
        r"'(\w)'", re.search(r"ACTION_OUTPUT_KINDS\[\]\s*=\s*\{([^}]*)\}", draw).group(1)
    )
    assert len(kinds) == len(ACTION_TYPES) and kinds[-1] == 'V'


def test_node_takes_one_video_socket_from_the_catalog_contract():
    from mixar.modules.moodboard.core.node_schema import build_input_contract

    contract = build_input_contract(_service(), {})
    assert [socket["id"] for socket in contract["sockets"]] == ["video"]
    socket = contract["sockets"][0]
    assert socket["accepted_types"] == ["VIDEO"]
    assert socket["required"] is True and socket["repeatable"] is False
    assert contract["limits"] == {"VIDEO": 1}


def test_menus_offer_upscale_only_where_a_video_can_feed_it():
    menus = _read(MOODBOARD / "ui/moodboard_menus.py")
    node_menus = _read(MOODBOARD / "ui/moodboard_node_menus.py")

    output_menu = menus[menus.index("class MIXIE_MT_moodboard_output_menu"):]
    assert "if source_type == 'VIDEO' and _capability_available(\"video_upscale\")" in output_menu
    assert "'VIDEO_UPSCALE', \"Upscale Video\"" in output_menu

    context_menu = menus[: menus.index("class MIXIE_MT_moodboard_output_menu")]
    assert "'IMAGE_GEN', 'VIDEO_GEN', 'VIDEO_UPSCALE'" in context_menu
    assert "{'VIDEO_GEN', 'VIDEO_UPSCALE'}" in context_menu
    assert "selected_images > selected_stills and _capability_available(\"video_upscale\")" in context_menu
    assert "_capability_available(\"video_upscale\")" in node_menus
    assert "allow_empty=True" in node_menus[node_menus.index("'VIDEO_UPSCALE'"):]


def test_create_connected_action_keeps_only_one_movie_for_upscale():
    from mixar.modules.moodboard.core import node_graph

    still = SimpleNamespace(selected=True, image=SimpleNamespace(source='FILE'))
    movie_a = SimpleNamespace(selected=True, image=SimpleNamespace(source='MOVIE'))
    movie_b = SimpleNamespace(selected=True, image=SimpleNamespace(source='MOVIE'))
    scene = SimpleNamespace(mixie_moodboard_images=[still, movie_a, movie_b])

    assert node_graph._selected_media(scene, 'VIDEO_UPSCALE') == [movie_a]
    assert node_graph._selected_media(scene, 'VIDEO_GEN') == [still, movie_a, movie_b]
