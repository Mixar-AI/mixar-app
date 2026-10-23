# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""web_publish pure logic: publish_state helpers, the thread-safe state,
API parsing and the worker's workspace cleanup. Runs outside Blender (the
root conftest stubs bpy). Agent API, export spec and network-contract pins
live in ``test_web_publish_agent.py``.
"""

import hashlib
import math
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from mixar.modules.web_publish.core.publish_api import (
    ScenePublishService,
    parse_scene_payload,
    unwrap,
)
from mixar.modules.web_publish.core.publish_state import (
    STATUS_CANCELLED,
    STATUS_DONE,
    STATUS_ERROR,
    STATUS_EXPORTING,
    STATUS_IDLE,
    STATUS_UPLOADING,
    PublishJob,
    PublishResult,
    PublishState,
    build_scene_meta,
    camera_pose_to_config,
    compute_sha256,
    derive_title,
    part_ranges,
    suggest_slug,
    viewer_config_block,
)


class _Col:
    def __init__(self, values):
        self._v = values

    def __getitem__(self, i):
        return self._v[i]


class _Matrix:
    def __init__(self, columns):
        self.col = [_Col(c) for c in columns]


def _fake_client(data):
    """An HTTPClient stand-in whose every verb answers ``data``."""
    client = MagicMock()
    for verb in ("get", "post", "patch", "delete", "put"):
        getattr(client, verb).return_value = SimpleNamespace(data=data)
    client._base_url = "https://api.example.com"
    return client


class TestDeriveTitle:
    def test_plain_name(self):
        assert derive_title("MyScene") == "MyScene"

    def test_numbered_scene_suffix_removed(self):
        assert derive_title("Scene.001") == "Scene"

    def test_underscores_spaced(self):
        assert derive_title("cool_city_block") == "cool city block"

    def test_empty_falls_back(self):
        assert derive_title("") == "Untitled Scene"
        assert derive_title("   ") == "Untitled Scene"


class TestSuggestSlug:
    def test_basic(self):
        assert suggest_slug("My Cool Scene!") == "my-cool-scene"

    def test_unicode_folds_to_fallback(self):
        assert suggest_slug("日本語") == "scene"

    def test_length_clamped(self):
        assert len(suggest_slug("x" * 500)) <= 80


class TestComputeSha256:
    def test_matches_known_vector(self, tmp_path):
        body = b"glTF" + b"\x00" * 10_000
        target = tmp_path / "scene.glb"
        target.write_bytes(body)
        assert compute_sha256(str(target)) == (hashlib.sha256(body).hexdigest(), len(body))


class TestCameraPoseToConfig:
    def test_translation_and_look_in_gltf_axes(self):
        # Blender (x, y, z) Z-up → glTF / three.js (x, z, -y) Y-up, the frame
        # the exported GLB and the viewer use.
        matrix = _Matrix([(1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0),
                          (0.0, 0.0, 1.0, 0.0), (3.0, 4.0, 5.0, 1.0)])
        config = camera_pose_to_config(matrix, 50.0, 36.0, aspect=1.0)
        assert config["position"] == [3.0, 5.0, -4.0]
        # The camera looks down Blender -Z, i.e. three.js -Y.
        assert config["target"] == pytest.approx([3.0, 5.0 - 10.0, -4.0])
        assert config["up"] == [0.0, 1.0, 0.0]
        # Square frame: vertical FOV equals the sensor-width FOV.
        expected = math.degrees(2 * math.atan(36.0 / 100.0))
        assert config["fov"] == pytest.approx(expected, rel=0.01)

    def test_fov_is_vertical_for_three_js(self):
        from mixar.modules.web_publish.core.publish_state import vertical_fov_degrees

        horizontal = 2 * math.atan(36.0 / 100.0)
        landscape = vertical_fov_degrees(50.0, 36.0, 24.0, "AUTO", 16 / 9)
        assert landscape == pytest.approx(
            math.degrees(2 * math.atan(math.tan(horizontal / 2) / (16 / 9))))
        # Portrait AUTO: the sensor width spans the (larger) height.
        assert vertical_fov_degrees(50.0, 36.0, 24.0, "AUTO", 0.5) == pytest.approx(
            math.degrees(horizontal))
        assert vertical_fov_degrees(50.0, 36.0, 24.0, "VERTICAL", 16 / 9) == pytest.approx(
            math.degrees(2 * math.atan(24.0 / 100.0)))
        assert vertical_fov_degrees(0.0, 36.0) is None

    def test_lens_zero_omits_fov(self):
        matrix = _Matrix([(1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)])
        assert "fov" not in camera_pose_to_config(matrix, 0.0, 0.0)


class TestViewerConfigBlock:
    def test_defaults_without_camera(self):
        config = viewer_config_block(None)
        assert config["nav"] == ["orbit", "walk"]
        assert "camera" not in config

    def test_camera_included_when_given(self):
        assert viewer_config_block({"position": [0, 0, 5]})["camera"]["position"] == [0, 0, 5]


class TestBuildSceneMeta:
    def test_negative_clamped(self):
        meta = build_scene_meta(-1, -5, 2, 0, False)
        assert (meta["objects"], meta["triangles"], meta["materials"], meta["animations"]) == (0, 0, 2, 0)

    def test_animation_flag(self):
        assert build_scene_meta(1, 1, 1, 1, True)["animations"] == 1


class TestPartRanges:
    def test_exact_multiples(self):
        assert part_ranges(16, 8) == [(1, 0, 8), (2, 8, 8)]

    def test_remainder_tail(self):
        assert part_ranges(20, 8) == [(1, 0, 8), (2, 8, 8), (3, 16, 4)]

    def test_empty_file(self):
        assert part_ranges(0, 8) == []

    def test_matches_backend_plan_count(self):
        size, part_size = 100 * 1024 * 1024, 8 * 1024 * 1024
        assert len(part_ranges(size, part_size)) == (size + part_size - 1) // part_size


class TestParseScenePayload:
    def test_normalizes_and_anchors_relative_urls(self):
        payload = parse_scene_payload({
            "id": "abc", "slug": "my-scene", "revision": 3, "status": "ready",
            "share_url": "/api/v1/scene-publish/s/my-scene",
            "viewer_url": "https://scenes.mixar.app/s/my-scene",
        }, "https://api.mixar.app/")
        assert payload["id"] == "abc" and payload["revision"] == 3
        assert payload["share_url"] == "https://api.mixar.app/api/v1/scene-publish/s/my-scene"
        assert payload["viewer_url"] == "https://scenes.mixar.app/s/my-scene"

    def test_missing_fields(self):
        payload = parse_scene_payload({})
        assert (payload["id"], payload["revision"], payload["status"]) == ("", 0, "")


class TestPublishState:
    def test_lifecycle(self):
        state = PublishState()
        assert state.busy is False
        state.start()
        assert state.busy is True
        assert state.snapshot()[0].status == STATUS_EXPORTING
        state.set_upload_progress(500, 1000)
        progress, _ = state.snapshot()
        assert progress.status == STATUS_UPLOADING
        assert progress.progress == pytest.approx(0.5)
        state.set_result(PublishResult(slug="s", scene_id="id", revision=2))
        progress, result = state.snapshot()
        assert progress.status == STATUS_DONE and result.slug == "s"
        assert state.busy is False

    def test_error_is_terminal(self):
        state = PublishState()
        state.start()
        state.set_error("boom")
        progress, _ = state.snapshot()
        assert progress.status == STATUS_ERROR and progress.error == "boom"
        assert state.busy is False
        # A late progress write from the worker never resurrects it.
        state.set_upload_progress(1, 2)
        assert state.snapshot()[0].status == STATUS_ERROR

    def test_progress_clamped(self):
        state = PublishState()
        state.set_status(STATUS_UPLOADING, progress=7.0)
        assert state.snapshot()[0].progress == 1.0
        state.set_status(STATUS_EXPORTING, progress=float("nan"))
        assert state.snapshot()[0].progress == 0.0

    def test_cancel_flag(self):
        state = PublishState()
        assert state.cancel_requested is False
        state.request_cancel()
        assert state.cancel_requested is True
        state.start()
        assert state.cancel_requested is False

    def test_reset_clears_error(self):
        state = PublishState()
        state.set_error("x")
        state.reset()
        assert state.snapshot()[0].status == STATUS_IDLE

    def test_begin_claims_the_single_slot(self):
        # #1360 marked the state busy and then refused its own worker; the
        # claim is now one atomic step and a second publish is refused.
        state = PublishState()
        assert state.begin("a", "Scene") is True
        assert state.begin("b", "Scene") is False
        state.set_cancelled()
        assert state.snapshot()[0].status == STATUS_CANCELLED
        assert state.begin("b", "Other") is True and state.scene_name == "Other"

    def test_templates_are_formatted_lazily(self):
        state = PublishState()
        state.begin("a")
        state.set_status(STATUS_UPLOADING, "Uploading part {index} of {count}…", 0.3,
                         index=2, count=5)
        progress, _ = state.snapshot()
        assert progress.detail == "Uploading part {index} of {count}…"
        assert progress.detail_text == "Uploading part 2 of 5…"


class TestThreadSafety:
    def test_concurrent_writers_keep_state_consistent(self):
        state = PublishState()
        errors = []

        def writer(base: int):
            try:
                for i in range(200):
                    state.set_upload_progress(base + i, 10_000)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(t * 1000,)) for t in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert not errors
        assert 0.0 <= state.snapshot()[0].progress <= 1.0


class TestApiClient:
    def test_unwrap_success_envelope(self):
        assert unwrap({"status": "success", "message": "OK",
                       "data": {"scene": {"id": "123"}}}) == {"scene": {"id": "123"}}

    def test_unwrap_direct_payload(self):
        assert unwrap({"scene": {"id": "123"}}) == {"scene": {"id": "123"}}

    def test_init_publish_handles_enveloped_and_unwrapped(self):
        service = ScenePublishService(_fake_client(
            {"status": "success", "data": {"scene": {"id": "s1"}, "upload": {"mode": "put"}}}))
        assert service.init_publish({}) == ({"id": "s1"}, {"mode": "put"})
        service = ScenePublishService(_fake_client(
            {"scene": {"id": "s2"}, "upload": {"mode": "multipart"}}))
        assert service.init_publish({}) == ({"id": "s2"}, {"mode": "multipart"})
        assert service._client.post.call_args[0][0] == "api/v1/scene-publish/scenes"

    def test_upload_thumbnail_sends_ext_query_param(self, tmp_path):
        thumb = tmp_path / "thumb.png"
        thumb.write_bytes(b"png-bytes")
        client = _fake_client({"status": "success", "message": "ok", "data": {}})
        scene_id = "8f14e45f-ceea-467a-9575-1a2b3c4d5e6f"
        ScenePublishService(client).upload_thumbnail(scene_id, str(thumb))
        args, kwargs = client.post.call_args
        assert args[0] == f"api/v1/scene-publish/scenes/{scene_id}/thumbnail"
        assert kwargs["params"] == {"ext": ".png"} and kwargs["data"] == b"png-bytes"


class TestWorkerWorkspaceCleanup:
    def test_run_cleans_up_workspace_on_error(self, tmp_path):
        from mixar.modules.web_publish.core import upload_worker
        from mixar.modules.web_publish.core.publish_state import get_publish_state

        ws = tmp_path / "mixar_web_publish_test"
        ws.mkdir()
        glb = ws / "scene.glb"
        glb.write_bytes(b"fake")
        job = PublishJob(title="T", description="", visibility="public", glb_path=str(glb),
                         thumbnail_path="", content_sha256="a" * 64)
        service = MagicMock()
        service.init_publish.side_effect = RuntimeError("Simulated failure")
        get_publish_state().begin("cleanup")
        upload_worker._run(job, str(ws), service)
        assert not ws.exists(), "the worker's finally must remove the workspace"
        progress, _ = get_publish_state().snapshot()
        assert progress.status == STATUS_ERROR and "RuntimeError" in progress.error_text
