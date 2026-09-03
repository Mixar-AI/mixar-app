# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for web_publish pure logic (publish_state + api parsing).

Runs outside Blender — the root conftest installs bpy stubs, but these modules
never import bpy.
"""

import math
import threading

import pytest

from mixar.modules.web_publish.core.publish_api import parse_scene_payload
from mixar.modules.web_publish.core.publish_state import (
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
        import hashlib

        target = tmp_path / "scene.glb"
        target.write_bytes(b"glTF" + b"\x00" * 10_000)
        expected = hashlib.sha256(b"glTF" + b"\x00" * 10_000).hexdigest()
        digest, size = compute_sha256(str(target))
        assert digest == expected
        assert size == len(b"glTF" + b"\x00" * 10_000)


class TestCameraPoseToConfig:
    def test_translation_and_look(self):
        # Build a 4x4 in the stub world: camera at origin looking -Z.
        class Col:
            def __init__(self, values):
                self._v = values

            def __getitem__(self, i):
                return self._v[i]

        class Matrix:
            def __init__(self):
                self.col = [
                    Col((1.0, 0.0, 0.0, 0.0)),
                    Col((0.0, 1.0, 0.0, 0.0)),
                    Col((0.0, 0.0, 1.0, 0.0)),
                    Col((3.0, 4.0, 5.0, 1.0)),
                ]

        config = camera_pose_to_config(Matrix(), 50.0, 36.0)
        assert config["position"] == [3.0, 4.0, 5.0]
        # Camera +Z basis is +Z world; look direction is -Z world.
        assert config["target"][2] == pytest.approx(5.0 - 10.0)
        assert config["target"][0] == pytest.approx(3.0)
        assert config["target"][1] == pytest.approx(4.0)
        # 36mm sensor + 50mm lens → ~39.6° vertical FOV (2*atan(36/(2*50)))
        assert config["fov"] == pytest.approx(math.degrees(2 * math.atan(36.0 / 100.0)), rel=0.01)

    def test_lens_zero_omits_fov(self):
        class Col:
            def __init__(self, values):
                self._v = values

            def __getitem__(self, i):
                return self._v[i]

        class Matrix:
            def __init__(self):
                self.col = [Col((1, 0, 0, 0)), Col((0, 1, 0, 0)),
                            Col((0, 0, 1, 0)), Col((0, 0, 0, 1))]

        config = camera_pose_to_config(Matrix(), 0.0, 0.0)
        assert "fov" not in config


class TestViewerConfigBlock:
    def test_defaults_without_camera(self):
        config = viewer_config_block(None)
        assert config["nav"] == ["orbit", "walk"]
        assert "camera" not in config

    def test_camera_included_when_given(self):
        config = viewer_config_block({"position": [0, 0, 5]})
        assert config["camera"]["position"] == [0, 0, 5]


class TestBuildSceneMeta:
    def test_negative_clamped(self):
        meta = build_scene_meta(-1, -5, 2, 0, False)
        assert meta["objects"] == 0
        assert meta["triangles"] == 0
        assert meta["materials"] == 2
        assert meta["animations"] == 0

    def test_animation_flag(self):
        assert build_scene_meta(1, 1, 1, 1, True)["animations"] == 1


class TestPartRanges:
    def test_exact_multiples(self):
        ranges = part_ranges(16, 8)
        assert ranges == [(1, 0, 8), (2, 8, 8)]

    def test_remainder_tail(self):
        ranges = part_ranges(20, 8)
        assert ranges == [(1, 0, 8), (2, 8, 8), (3, 16, 4)]

    def test_empty_file(self):
        assert part_ranges(0, 8) == []

    def test_matches_backend_plan_count(self):
        size = 100 * 1024 * 1024
        part_size = 8 * 1024 * 1024
        client_parts = (size + part_size - 1) // part_size
        assert len(part_ranges(size, part_size)) == client_parts


class TestParseScenePayload:
    def test_normalizes(self):
        payload = parse_scene_payload(
            {
                "id": "abc",
                "slug": "my-scene",
                "share_url": "/api/v1/scene-publish/s/my-scene",
                "viewer_url": "https://scenes.mixar.app/s/my-scene",
                "revision": 3,
                "status": "ready",
            }
        )
        assert payload["id"] == "abc"
        assert payload["revision"] == 3

    def test_missing_fields(self):
        payload = parse_scene_payload({})
        assert payload["id"] == ""
        assert payload["revision"] == 0
        assert payload["status"] == ""


class TestPublishState:
    def test_lifecycle(self):
        state = PublishState()
        assert state.busy is False

        state.start()
        assert state.busy is True
        progress, result = state.snapshot()
        assert progress.status == STATUS_EXPORTING

        state.set_upload_progress(500, 1000)
        progress, _ = state.snapshot()
        assert progress.status == STATUS_UPLOADING
        assert progress.progress == pytest.approx(0.5)

        state.set_result(PublishResult(slug="s", scene_id="id", revision=2))
        progress, result = state.snapshot()
        assert progress.status == STATUS_DONE
        assert result.slug == "s"
        assert state.busy is False

    def test_error_is_terminal(self):
        state = PublishState()
        state.start()
        state.set_error("boom")
        progress, _ = state.snapshot()
        assert progress.status == STATUS_ERROR
        assert progress.error == "boom"
        assert state.busy is False

    def test_progress_clamped(self):
        state = PublishState()
        state.set_status(STATUS_UPLOADING, progress=7.0)
        progress, _ = state.snapshot()
        assert progress.progress == 1.0

        state.set_status(STATUS_EXPORTING, progress=float("nan"))
        progress, _ = state.snapshot()
        assert progress.progress == 0.0

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
        progress, _ = state.snapshot()
        assert progress.status == STATUS_IDLE


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
        progress, _ = state.snapshot()
        assert 0.0 <= progress.progress <= 1.0


class TestApiClient:
    def test_parse_success_envelope(self):
        from unittest.mock import MagicMock
        from mixar.modules.web_publish.core.publish_api import ScenePublishClient

        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "status": "success",
            "message": "OK",
            "data": {"scene": {"id": "123"}},
        }
        client = ScenePublishClient(server_url="https://api.example.com")
        parsed = client._parse(resp)
        assert parsed["status"] == "success"
        assert parsed["data"]["scene"]["id"] == "123"

    def test_parse_unwrapped_success(self):
        from unittest.mock import MagicMock
        from mixar.modules.web_publish.core.publish_api import ScenePublishClient

        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"scene": {"id": "123"}}
        client = ScenePublishClient(server_url="https://api.example.com")
        parsed = client._parse(resp)
        assert parsed["scene"]["id"] == "123"

    def test_init_publish_handles_enveloped_and_unwrapped(self):
        from unittest.mock import MagicMock
        from mixar.modules.web_publish.core.publish_api import ScenePublishClient

        client = ScenePublishClient(server_url="https://api.example.com")

        # Enveloped
        client._request = MagicMock(
            return_value={
                "status": "success",
                "data": {"scene": {"id": "s1"}, "upload": {"mode": "put"}},
            }
        )
        scene, upload = client.init_publish({})
        assert scene["id"] == "s1"
        assert upload["mode"] == "put"

        # Unwrapped
        client._request = MagicMock(
            return_value={"scene": {"id": "s2"}, "upload": {"mode": "multipart"}}
        )
        scene, upload = client.init_publish({})
        assert scene["id"] == "s2"
        assert upload["mode"] == "multipart"

    def test_upload_thumbnail_appends_ext_query_param(self, tmp_path):
        from unittest.mock import MagicMock
        from mixar.modules.web_publish.core.publish_api import ScenePublishClient

        thumb = tmp_path / "thumb.png"
        thumb.write_bytes(b"png-bytes")

        client = ScenePublishClient(server_url="https://api.example.com")
        client._request = MagicMock(return_value={"status": "success"})

        client.upload_thumbnail("scene-123", str(thumb))
        assert client._request.call_count == 1
        call_args = client._request.call_args
        assert call_args[0][0] == "POST"
        assert "scenes/scene-123/thumbnail?ext=.png" in call_args[0][1]


class TestWorkerWorkspaceCleanup:
    def test_run_cleans_up_workspace_on_error(self, tmp_path):
        from unittest.mock import patch
        from mixar.modules.web_publish.core.upload_worker import _run

        ws = tmp_path / "ws_test"
        ws.mkdir()
        dummy_file = ws / "scene.glb"
        dummy_file.write_bytes(b"fake")

        job = PublishJob(
            title="T",
            description="",
            visibility="public",
            glb_path=str(dummy_file),
            thumbnail_path="",
            content_sha256="a" * 64,
        )

        with patch("mixar.modules.web_publish.core.upload_worker.ScenePublishClient") as ClientCls:
            client = ClientCls.return_value
            client.init_publish.side_effect = RuntimeError("Simulated network failure")

            _run(job, str(ws))

        assert not ws.exists(), "Workspace directory should have been cleaned up in finally block"

