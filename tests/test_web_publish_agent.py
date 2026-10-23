# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Publish to Web contracts pinned outside Blender:

- the export goes through the SHARED agent export lane with
  ``use_case=web / format=glb / target_scope=scene`` and the
  ``web_publish`` profile (Draco 6, WebP, modifiers applied);
- ``agent_api`` return shapes (docs/modules/web-publish.md § Agent API);
- transport failures route through ``classify_network_error``;
- the worker's upload, cancel and error paths.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests

from mixar.modules.space_mixie_chat.core import export_presets
from mixar.modules.web_publish.core import agent_api, glb_export, publish_api, upload_worker
from mixar.modules.web_publish.core.publish_api import PublishApiError, ScenePublishService
from mixar.modules.web_publish.core.publish_state import (
    STATUS_CANCELLED,
    STATUS_DONE,
    PublishJob,
    PublishResult,
    get_publish_state,
)

_STATUS_KEYS = {"status", "progress", "share_url", "slug", "error", "warning"}


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    from mixar.modules.web_publish.core import links, publish_state

    monkeypatch.setattr(publish_state, "_state", publish_state.PublishState())
    monkeypatch.setattr(links, "trusted_hosts",
                        lambda api_url=None: ("api.mixar.app", "mixar.app"))
    yield


# -- export spec ----------------------------------------------------------------


def test_publish_export_spec_is_the_shared_web_scene_glb():
    spec = glb_export.build_export_spec(["Chair", "Table"], include_animation=True)
    assert spec["use_case"] == "web" and spec["format"] == "glb"
    assert spec["target_scope"] == "scene" and spec["profile"] == "web_publish"
    assert spec["mesh_names"] == ["Chair", "Table"]  # visible meshes only
    assert spec["animations"] is None  # every clip
    assert glb_export.build_export_spec([], include_animation=False)["animations"] == []


def test_web_publish_profile_adds_draco_and_webp_on_top_of_the_web_preset():
    web = export_presets.preset_kwargs("web", "glb")
    publish = export_presets.preset_kwargs("web", "glb", "web_publish")
    assert publish["export_draco_mesh_compression_enable"] is True
    assert publish["export_draco_mesh_compression_level"] == 6
    assert publish["export_image_format"] == "WEBP"
    assert publish["export_apply"] is True
    # Everything #1807 fixed for three.js is kept.
    for key in ("export_cameras", "export_lights", "export_import_convert_lighting_mode",
                "export_extras", "use_active_scene", "use_selection"):
        assert publish[key] == web[key], key
    # The plain web preset (agent export_scene) is unchanged; unknown
    # profiles and non-glTF families get no overrides.
    assert web["export_draco_mesh_compression_enable"] is False
    assert export_presets.preset_kwargs("web", "glb", "nope") == web
    assert export_presets.preset_kwargs("web", "fbx", "web_publish") == \
        export_presets.preset_kwargs("web", "fbx")


def test_export_glb_delegates_to_export_to_path(monkeypatch):
    from mixar.modules.space_mixie_chat.core import agent_export

    calls = []

    def fake_export(filepath, spec, *, via, tool):
        calls.append((filepath, spec, via, tool))
        return {"success": True, "warning": "World not carried"}

    monkeypatch.setattr(agent_export, "export_to_path", fake_export)
    meshes = [SimpleNamespace(name="Chair")]
    no_camera = SimpleNamespace(camera=None)
    result = glb_export.export_glb("/tmp/x/scene.glb", meshes, include_animation=False,
                                   scene=no_camera)
    assert result["warning"] == "World not carried"
    filepath, spec, via, tool = calls[0]
    assert filepath.endswith("scene.glb") and via == "web_publish" and tool == "publish_to_web"
    assert spec == glb_export.build_export_spec(["Chair"], False)

    monkeypatch.setattr(agent_export, "export_to_path",
                        lambda *a, **k: {"success": False, "error": "Exporter returned CANCELLED"})
    with pytest.raises(glb_export.ExportError, match="CANCELLED"):
        glb_export.export_glb("/tmp/x/scene.glb", meshes, scene=no_camera)
    with pytest.raises(glb_export.ExportError):
        glb_export.export_glb("/tmp/x/scene.glb", [], scene=no_camera)


def test_visible_meshes_skip_render_disabled_collections():
    def mesh(name, hidden_collection=False, hide_render=False):
        return SimpleNamespace(name=name, type="MESH", hide_render=hide_render,
                               visible_get=lambda: True,
                               users_collection=[SimpleNamespace(hide_render=False),
                                                 SimpleNamespace(hide_render=hidden_collection)])

    scene = SimpleNamespace(objects=[mesh("Shown"), mesh("InHiddenCol", hidden_collection=True),
                                     mesh("HiddenObj", hide_render=True)])
    assert [m.name for m in glb_export.visible_meshes(scene)] == ["Shown"]


class _Camera(dict):
    """An ID-property bag like ``bpy.types.Object``."""


def test_active_camera_is_tagged_for_the_export_only(monkeypatch):
    from mixar.modules.space_mixie_chat.core import agent_export

    camera = _Camera()
    seen = []
    monkeypatch.setattr(agent_export, "export_to_path", lambda *a, **k: seen.append(
        dict(camera)) or {"success": True})
    glb_export.export_glb("/tmp/x/scene.glb", [SimpleNamespace(name="Chair")],
                          scene=SimpleNamespace(camera=camera))
    assert seen == [{"mixar_active_camera": True}]  # the viewer's home camera
    assert camera == {}  # removed afterwards: the .blend is left as found

    camera["mixar_active_camera"] = "user value"
    monkeypatch.setattr(agent_export, "export_to_path",
                        lambda *a, **k: {"success": False, "error": "boom"})
    with pytest.raises(glb_export.ExportError):
        glb_export.export_glb("/tmp/x/scene.glb", [SimpleNamespace(name="Chair")],
                              scene=SimpleNamespace(camera=camera))
    assert camera == {"mixar_active_camera": "user value"}


# -- agent_api -----------------------------------------------------------------


def test_start_publish_shapes(monkeypatch):
    from mixar.modules.web_publish.core import pipeline

    seen = {}

    def fake_begin(context, **kwargs):
        seen.update(kwargs)
        return {"ok": True, "publish_id": "abc123"}

    monkeypatch.setattr(pipeline, "begin_publish", fake_begin)
    out = agent_api.start_publish({"title": "Loft", "description": "d",
                                   "update_existing": "true", "include_animation": False})
    assert out == {"publish_id": "abc123", "status": "started"}
    assert seen == {"title": "Loft", "description": "d", "update_existing": True,
                    "include_animation": False, "visibility": None, "via": "agent"}
    # Omitted options defer to the panel settings (None), never invented.
    agent_api.start_publish({})
    assert seen["title"] is None and seen["include_animation"] is None
    assert seen["update_existing"] is False

    monkeypatch.setattr(pipeline, "begin_publish", lambda context, **k: {
        "ok": False, "error": "Titles are limited to {limit} characters",
        "error_args": {"limit": 140}})
    assert agent_api.start_publish({"title": "x"}) == {
        "publish_id": None, "status": "failed", "error": "Titles are limited to 140 characters"}

    def boom(context, **kwargs):
        raise RuntimeError("/Users/someone/secret path")

    monkeypatch.setattr(pipeline, "begin_publish", boom)
    out = agent_api.start_publish(None)
    assert out["status"] == "failed" and "/" not in out["error"]


def test_publish_status_shapes_across_the_lifecycle():
    state = get_publish_state()
    unknown = agent_api.publish_status("missing")
    assert set(unknown) == _STATUS_KEYS and unknown["status"] == "failed"

    assert state.begin("p1", "Scene")
    out = agent_api.publish_status("p1")
    assert set(out) == _STATUS_KEYS and out["status"] == "exporting"
    assert out["share_url"] is None and out["error"] is None

    state.set_warning("1 area light(s) have no glTF equivalent")
    state.set_status("FINALIZING", "Uploading thumbnail…", 0.96)
    out = agent_api.publish_status({"publish_id": "p1"})  # __PARAMS__ passed whole
    assert out["status"] == "uploading" and out["progress"] == pytest.approx(0.96)
    assert out["warning"].startswith("1 area light")

    state.set_result(PublishResult(scene_id="id", slug="loft", revision=1,
                                   share_url="https://api.mixar.app/s/loft", viewer_url="https://scenes.mixar.app/s/loft"))
    ready = agent_api.publish_status("p1")
    assert ready["status"] == "ready" and ready["progress"] == 1.0
    assert ready["share_url"] == "https://api.mixar.app/s/loft" and ready["slug"] == "loft"
    # Dismissing the outcome in the panel never hides it from a late poll.
    state.reset()
    assert agent_api.publish_status("p1")["status"] == "ready"


def test_publish_status_reports_failed_and_cancelled_with_formatted_errors():
    state = get_publish_state()
    state.begin("p2")
    state.set_error("Upload failed after {attempts} attempts", attempts=3)
    failed = agent_api.publish_status("p2")
    assert failed["status"] == "failed" and failed["error"] == "Upload failed after 3 attempts"
    assert failed["share_url"] is None and failed["slug"] is None
    state.begin("p3")
    state.set_cancelled()
    assert agent_api.publish_status("p3")["status"] == "cancelled"
    assert agent_api.publish_status("p2")["status"] == "failed"  # earlier record kept


# -- network contract -------------------------------------------------------------


def _client_raising(exc):
    client = MagicMock()
    client.post.side_effect = exc
    client._base_url = "https://api.example.com"
    return client


def test_backend_transport_failure_is_classified(monkeypatch):
    from mixar.modules.common.api.exceptions import ConnectionError as ApiConnectionError

    seen = []
    real = publish_api.classify_network_error
    monkeypatch.setattr(publish_api, "classify_network_error",
                        lambda exc, url=None: seen.append((exc, url)) or real(exc, url))
    monkeypatch.setattr(publish_api, "log_network_failure", lambda *a, **k: None)
    try:
        raise requests.exceptions.ConnectionError("Name or service not known")
    except requests.exceptions.ConnectionError as cause:
        wrapped = ApiConnectionError("Failed to connect")
        wrapped.__cause__ = cause
    service = ScenePublishService(_client_raising(wrapped))
    with pytest.raises(PublishApiError) as info:
        service.init_publish({"title": "x"})
    assert info.value.code == "network" and info.value.support_code.startswith("NET-")
    assert seen and seen[0][1].endswith("api/v1/scene-publish/scenes")
    assert "Unable to connect" not in info.value.message


def test_presigned_put_failure_is_classified_without_the_signature(monkeypatch, tmp_path):
    glb = tmp_path / "scene.glb"
    glb.write_bytes(b"glTF" + b"\x00" * 64)
    urls = []
    monkeypatch.setattr(publish_api, "classify_network_error",
                        lambda exc, url=None: urls.append(url) or SimpleNamespace(
                            message="Connection timed out", support_code="NET-TIMEOUT"))
    monkeypatch.setattr(publish_api, "log_network_failure", lambda *a, **k: None)

    def put(*args, **kwargs):
        raise requests.exceptions.ReadTimeout("read timed out")

    monkeypatch.setattr(publish_api.requests, "put", put)
    with pytest.raises(PublishApiError) as info:
        publish_api.put_object("https://s3.example/k?X-Amz-Signature=secret", str(glb), 68,
                               "model/gltf-binary")
    assert info.value.code == "network" and info.value.support_code == "NET-TIMEOUT"
    assert urls == ["https://s3.example/k"]


def test_backend_error_codes_survive_both_body_shapes():
    from mixar.modules.common.api.exceptions import AuthorizationError, ValidationError

    detail = {"detail": {"status": "failure", "message": "Publish limit reached (25 scenes).",
                         "data": {"code": "scene_quota_exceeded"}}}
    service = ScenePublishService(_client_raising(
        AuthorizationError(message="x", status_code=403, response_data=detail)))
    with pytest.raises(PublishApiError) as info:
        service.init_publish({})
    assert info.value.code == "scene_quota_exceeded" and info.value.status_code == 403
    assert info.value.message == "{message}"
    assert info.value.params == {"message": "Publish limit reached (25 scenes)."}

    bare = {"status": "failure", "message": "Too big", "data": {"code": "scene_too_large"}}
    service = ScenePublishService(_client_raising(
        ValidationError(message="x", status_code=413, response_data=bare)))
    with pytest.raises(PublishApiError) as info:
        service.init_publish({})
    assert info.value.code == "scene_too_large"


# -- worker -----------------------------------------------------------------------


def _job(tmp_path, existing=""):
    ws = tmp_path / "mixar_web_publish_job"
    ws.mkdir()
    glb = ws / "scene.glb"
    glb.write_bytes(b"glTF" + b"\x00" * 128)
    job = PublishJob(title="Loft", description="", visibility="public", glb_path=str(glb),
                     thumbnail_path="", content_sha256="b" * 64,
                     existing_scene_id=existing, existing_slug="loft" if existing else "")
    return job, ws


def _service(mode="put"):
    service = MagicMock()
    service.base_url = "https://api.mixar.app"
    service.init_publish.return_value = ({"id": "s1", "slug": "loft"},
                                         {"mode": mode, "url": "https://s3/put"})
    service.complete_upload.return_value = {"id": "s1", "slug": "loft", "revision": 1,
                                            "share_url": "/api/v1/scene-publish/s/loft"}
    return service


def test_worker_put_path_reaches_ready_with_an_absolute_link(tmp_path, monkeypatch):
    job, ws = _job(tmp_path)
    service = _service()
    puts = []
    monkeypatch.setattr(publish_api, "put_object", lambda *a, **k: puts.append(a))
    get_publish_state().begin("w1")
    upload_worker._run(job, str(ws), service)
    progress, result = get_publish_state().snapshot()
    assert progress.status == STATUS_DONE, progress
    assert result.share_url == "https://api.mixar.app/api/v1/scene-publish/s/loft"
    assert puts and puts[0][3] == "model/gltf-binary"
    assert "slug" not in service.init_publish.call_args[0][0]  # first publish
    assert not ws.exists()


def test_cancel_discards_a_first_publish_draft_but_never_a_revision(tmp_path, monkeypatch):
    def cancel_during_put(*args, **kwargs):
        get_publish_state().request_cancel()

    monkeypatch.setattr(publish_api, "put_object", cancel_during_put)
    job, ws = _job(tmp_path)
    service = _service()
    get_publish_state().begin("c1")
    upload_worker._run(job, str(ws), service)
    assert get_publish_state().snapshot()[0].status == STATUS_CANCELLED
    service.delete_scene.assert_called_once_with("s1")
    service.complete_upload.assert_not_called()

    revision_dir = tmp_path / "rev"
    revision_dir.mkdir()
    job, ws = _job(revision_dir, existing="s1")
    service = _service()
    get_publish_state().begin("c2")
    upload_worker._run(job, str(ws), service)
    assert get_publish_state().snapshot()[0].status == STATUS_CANCELLED
    assert service.init_publish.call_args[0][0]["slug"] == "loft"
    service.delete_scene.assert_not_called()


def test_publish_telemetry_carries_exactly_the_allowlisted_keys(monkeypatch):
    from mixar.modules.common.analytics import web_publish_events

    events = []
    monkeypatch.setattr(web_publish_events, "capture",
                        lambda name, props, context=None: events.append((name, props)))
    web_publish_events.capture_publish_started("agent", True, False)
    web_publish_events.capture_publish_finished("mcp", "exploded")
    assert events == [
        ("web_publish.started", {"via": "agent", "update": True, "include_animation": False}),
        ("web_publish.finished", {"via": "other", "outcome": "failed"}),
    ]


# -- pipeline (main-thread half) -------------------------------------------------


def _props(**overrides):
    values = dict(title="", description="", visibility="public", include_animation=True,
                  published_scene_id="", slug="", share_url="", viewer_url="", revision=0,
                  last_published="")
    values.update(overrides)
    return SimpleNamespace(**values)


def test_begin_publish_refusals_never_export(monkeypatch):
    from mixar.modules.web_publish.core import pipeline

    exports = []
    monkeypatch.setattr(pipeline, "_signed_in", lambda: True)
    monkeypatch.setattr(pipeline.glb_export, "visible_meshes", lambda scene: [object()])
    monkeypatch.setattr(pipeline.glb_export, "export_glb", lambda *a, **k: exports.append(a))
    context = SimpleNamespace(scene=SimpleNamespace(name="Loft", mixar_web_publish=_props()))

    refused = pipeline.begin_publish(context, update_existing=True)
    assert refused["ok"] is False and "not been published" in refused["error"]
    refused = pipeline.begin_publish(context, title="x" * 141)
    assert refused == {"ok": False, "error": "Titles are limited to {limit} characters",
                       "error_args": {"limit": 140}}
    get_publish_state().begin("other", "Elsewhere")
    assert pipeline.begin_publish(context)["error"] == "A publish is already running"
    monkeypatch.setattr(pipeline, "_signed_in", lambda: False)
    assert "Sign in" in pipeline.begin_publish(context)["error"]
    assert exports == []


def test_workspace_failure_releases_publish_claim(monkeypatch):
    from mixar.modules.web_publish.core import pipeline

    monkeypatch.setattr(pipeline, "_signed_in", lambda: True)
    monkeypatch.setattr(pipeline, "_telemetry", lambda *a: None)
    monkeypatch.setattr(pipeline, "ensure_timer", lambda: None)
    monkeypatch.setattr(pipeline.glb_export, "visible_meshes", lambda scene: [object()])

    def disk_full():
        raise OSError("No space left on device")

    monkeypatch.setattr(pipeline.workspace, "make_export_workspace", disk_full)
    context = SimpleNamespace(scene=SimpleNamespace(name="Loft", mixar_web_publish=_props()))
    result = pipeline.begin_publish(context)
    assert result["ok"] is False
    state = get_publish_state()
    assert not state.busy
    assert state.snapshot()[0].status == "ERROR"
    assert state.begin("retry", "Loft", "panel")


def test_mirror_files_the_result_on_the_published_scene_not_the_shown_one(monkeypatch):
    from mixar.modules.web_publish.core import pipeline

    published, shown = _props(), _props()
    wm = SimpleNamespace(mixar_web_publish_status="IDLE", mixar_web_publish_progress=0.0,
                         mixar_web_publish_scene="", windows=[])
    fake_bpy = SimpleNamespace(
        context=SimpleNamespace(window_manager=wm,
                                scene=SimpleNamespace(mixar_web_publish=shown)),
        data=SimpleNamespace(scenes={"Loft": SimpleNamespace(mixar_web_publish=published)}),
    )
    monkeypatch.setattr(pipeline, "bpy", fake_bpy)
    monkeypatch.setattr(pipeline, "_telemetry", lambda *a: None)
    state = get_publish_state()
    state.begin("m1", "Loft", "panel")
    assert pipeline._mirror() is not None  # busy: keep polling
    assert wm.mixar_web_publish_status == "EXPORTING" and wm.mixar_web_publish_scene == "Loft"
    state.set_result(PublishResult(scene_id="id1", slug="loft", revision=2,
                                   share_url="https://api.mixar.app/s/loft"))
    assert pipeline._mirror() is None  # terminal: stop
    assert wm.mixar_web_publish_status == "DONE"
    assert (published.slug, published.revision, published.share_url) == \
        ("loft", 2, "https://api.mixar.app/s/loft")
    assert shown.slug == ""
    published.slug = "edited"
    pipeline._mirror()  # applied once per outcome
    assert published.slug == "edited"
