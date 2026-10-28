# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""PR #1843 review fixes, pinned outside Blender:

- a scene id from the .blend is a UUID or no publication (no path traversal
  into another API route with the user's token);
- export failures never carry a local path to the agent/backend;
- an outcome landing after a file load is dropped; an undo that blanks the
  record gets it back;
- an agent's new version omits ``visibility`` (the backend keeps it);
- a cancel interrupts a single presigned PUT mid-stream; a failed first
  publish deletes its draft.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from mixar.modules.web_publish.core import pipeline, publish_api, upload_worker
from mixar.modules.web_publish.core.publish_api import PublishApiError, ScenePublishService
from mixar.modules.web_publish.core.publish_state import (
    STATUS_CANCELLED,
    STATUS_ERROR,
    PublishJob,
    PublishResult,
    get_publish_state,
)

SCENE_ID = "8f14e45f-ceea-467a-9575-1a2b3c4d5e6f"
TRAVERSALS = ["../../asset-search/embeddings", "..", "a/b", "%2e%2e", "", None,
              SCENE_ID + "/../x"]


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    from mixar.modules.web_publish.core import links, publish_state

    monkeypatch.setattr(publish_state, "_state", publish_state.PublishState())
    monkeypatch.setattr(links, "trusted_hosts",
                        lambda api_url=None: ("api.mixar.app", "mixar.app"))
    monkeypatch.setattr(pipeline, "_load_generation", 0)
    monkeypatch.setattr(pipeline, "_last_applied", {})
    monkeypatch.setattr(pipeline, "_telemetry", lambda *a: None)
    monkeypatch.setattr(pipeline, "ensure_timer", lambda: None)
    monkeypatch.setattr(pipeline, "_ensure_handlers", lambda: None)


def _props(**overrides):
    values = dict(title="", description="", visibility="public", include_animation=True,
                  published_scene_id="", slug="", share_url="", viewer_url="", revision=0,
                  last_published="")
    values.update(overrides)
    return SimpleNamespace(**values)


# -- 1. scene ids are UUIDs or nothing ----------------------------------------------


@pytest.mark.parametrize("scene_id", TRAVERSALS)
def test_a_non_uuid_scene_id_never_produces_a_request(scene_id, tmp_path):
    thumb = tmp_path / "t.png"
    thumb.write_bytes(b"png")
    client = MagicMock()
    service = ScenePublishService(client)
    calls = [
        lambda: service.delete_scene(scene_id),
        lambda: service.get_scene(scene_id),
        lambda: service.update_scene(scene_id, {"title": "x"}),
        lambda: service.complete_upload(scene_id, None, None, "a" * 64),
        lambda: service.upload_thumbnail(scene_id, str(thumb)),
    ]
    for call in calls:
        with pytest.raises(PublishApiError) as info:
            call()
        assert info.value.code == "invalid_scene_id"
    for method in ("get", "post", "patch", "put", "delete"):
        getattr(client, method).assert_not_called()


def test_a_uuid_scene_id_is_sent_canonical():
    client = MagicMock()
    client.delete.return_value = SimpleNamespace(data={"status": "success", "data": {}})
    ScenePublishService(client).delete_scene(" " + SCENE_ID.upper() + " ")
    assert client.delete.call_args[0][0] == f"api/v1/scene-publish/scenes/{SCENE_ID}"


def test_unpublish_with_a_crafted_id_clears_locally_without_a_request():
    props = _props(published_scene_id="../../asset-search/embeddings", slug="loft",
                   share_url="https://scenes.mixar.app/s/loft", revision=3)
    service = MagicMock()
    assert pipeline.unpublish(props, service) is None
    service.delete_scene.assert_not_called()
    assert (props.published_scene_id, props.slug, props.share_url, props.revision) == \
        ("", "", "", 0)


def test_unpublish_sends_the_canonical_id_and_keeps_the_record_on_failure():
    props = _props(published_scene_id=SCENE_ID.upper(), slug="loft")
    service = MagicMock()
    service.delete_scene.side_effect = PublishApiError("{message}", status_code=500,
                                                       params={"message": "down"})
    error = pipeline.unpublish(props, service)
    assert error is not None and error.status_code == 500
    service.delete_scene.assert_called_once_with(SCENE_ID)
    assert props.slug == "loft"  # not cleared: the site is still up
    service.delete_scene.side_effect = PublishApiError("gone", status_code=404)
    assert pipeline.unpublish(props, service) is None and props.slug == ""


def test_new_version_with_a_crafted_id_is_refused_before_export(monkeypatch):
    exports = []
    monkeypatch.setattr(pipeline, "_signed_in", lambda: True)
    monkeypatch.setattr(pipeline.glb_export, "visible_meshes", lambda scene: [object()])
    monkeypatch.setattr(pipeline.glb_export, "export_glb", lambda *a, **k: exports.append(a))
    props = _props(published_scene_id="../../asset-search/embeddings", slug="loft")
    context = SimpleNamespace(scene=SimpleNamespace(name="Loft", mixar_web_publish=props))
    refused = pipeline.begin_publish(context, update_existing=True, via="agent")
    assert refused["ok"] is False and "not been published" in refused["error"]
    assert exports == [] and not get_publish_state().busy


# -- begin_publish up to the worker hand-off -----------------------------------------


def _run_begin(monkeypatch, props, export=None, **kwargs):
    """``begin_publish`` with every Blender-side step faked; returns
    ``(outcome, job)`` where ``job`` is what reached the worker."""
    seen = {}
    monkeypatch.setattr(pipeline, "_signed_in", lambda: True)
    monkeypatch.setattr(pipeline.glb_export, "visible_meshes", lambda scene: [object()])
    monkeypatch.setattr(pipeline.workspace, "make_export_workspace",
                        lambda: ("/tmp/mixar_web_publish_t", "/tmp/mixar_web_publish_t/s.glb"))
    monkeypatch.setattr(pipeline.workspace, "cleanup_workspace", lambda folder: None)
    monkeypatch.setattr(pipeline.glb_export, "export_glb",
                        export or (lambda *a, **k: {"warning": ""}))
    monkeypatch.setattr(pipeline, "compute_sha256", lambda path: ("c" * 64, 10))
    monkeypatch.setattr(pipeline.thumbnail, "render_thumbnail", lambda scene, path: "")
    monkeypatch.setattr(pipeline.glb_export, "collect_scene_meta", lambda scene, meshes: {})
    monkeypatch.setattr(pipeline.glb_export, "collect_camera_config", lambda scene: {})
    monkeypatch.setattr(publish_api, "ScenePublishService", MagicMock())
    monkeypatch.setattr(upload_worker, "spawn",
                        lambda job, folder, service: seen.setdefault("job", job) and True)
    context = SimpleNamespace(scene=SimpleNamespace(name="Loft", mixar_web_publish=props))
    outcome = pipeline.begin_publish(context, **kwargs)
    return outcome, seen.get("job")


def test_new_version_sends_the_canonical_existing_id(monkeypatch):
    props = _props(published_scene_id=SCENE_ID.upper(), slug="loft")
    outcome, job = _run_begin(monkeypatch, props, update_existing=True)
    assert outcome["ok"] is True and job.existing_scene_id == SCENE_ID


# -- 3. no local path in an export failure ---------------------------------------------


def test_export_failure_text_carries_no_local_path(monkeypatch):
    def disk_full(*args, **kwargs):
        raise OSError(28, "No space left on device", "/tmp/x/scene.glb")

    outcome, _ = _run_begin(monkeypatch, _props(), export=disk_full, via="agent")
    message = outcome["error_args"]["message"]
    assert outcome["ok"] is False and "/tmp" not in message
    assert "No space left on device" in message
    assert "/tmp" not in get_publish_state().snapshot()[0].error_text


# -- 6. an agent's new version keeps the site's visibility ------------------------------


def test_agent_new_version_omits_visibility_unless_given(monkeypatch):
    published = dict(published_scene_id=SCENE_ID, slug="loft", visibility="public")
    _, job = _run_begin(monkeypatch, _props(**published), update_existing=True, via="agent")
    assert job.visibility == ""
    get_publish_state().set_error("reset")
    _, job = _run_begin(monkeypatch, _props(**published), update_existing=True, via="agent",
                        visibility="unlisted")
    assert job.visibility == "unlisted"
    get_publish_state().set_error("reset")
    _, job = _run_begin(monkeypatch, _props(visibility="unlisted"), via="agent")
    assert job.visibility == "unlisted"  # a first publish keeps the panel choice
    get_publish_state().set_error("reset")
    _, job = _run_begin(monkeypatch, _props(**published), update_existing=True, via="panel")
    assert job.visibility == "public"  # the panel always sends its setting


def _job(tmp_path, existing="", visibility="public"):
    ws = tmp_path / "mixar_web_publish_job"
    ws.mkdir()
    glb = ws / "scene.glb"
    glb.write_bytes(b"glTF" + b"\x00" * 4096)
    job = PublishJob(title="Loft", description="", visibility=visibility, glb_path=str(glb),
                     thumbnail_path="", content_sha256="b" * 64,
                     existing_scene_id=existing, existing_slug="loft" if existing else "")
    return job, ws


def _service(mode="put"):
    service = MagicMock()
    service.base_url = "https://api.mixar.app"
    service.init_publish.return_value = ({"id": SCENE_ID, "slug": "loft"},
                                         {"mode": mode, "url": "https://s3/put"})
    service.complete_upload.return_value = {"id": SCENE_ID, "slug": "loft", "revision": 1}
    return service


def test_worker_omits_an_empty_visibility(tmp_path, monkeypatch):
    monkeypatch.setattr(publish_api, "put_object", lambda *a, **k: None)
    job, ws = _job(tmp_path, existing=SCENE_ID, visibility="")
    service = _service()
    get_publish_state().begin("v1")
    upload_worker._run(job, str(ws), service)
    assert "visibility" not in service.init_publish.call_args[0][0]


def test_worker_omits_an_empty_description_on_a_new_version(tmp_path, monkeypatch):
    monkeypatch.setattr(publish_api, "put_object", lambda *a, **k: None)
    job, ws = _job(tmp_path, existing=SCENE_ID, visibility="")
    service = _service()
    get_publish_state().begin("v1")
    upload_worker._run(job, str(ws), service)
    assert "description" not in service.init_publish.call_args[0][0]


# -- 7. cancel mid-PUT; a failed first publish deletes its draft ------------------------


def test_cancel_interrupts_a_single_put_mid_stream(tmp_path, monkeypatch):
    reads = []

    def fake_put(url, data=None, headers=None, timeout=None):
        reads.append(len(data.read(1024)))
        get_publish_state().request_cancel()
        data.read(1024)  # the next read sees the cancel
        raise AssertionError("the body kept streaming after a cancel")

    monkeypatch.setattr(publish_api.requests, "put", fake_put)
    job, ws = _job(tmp_path)
    service = _service()
    get_publish_state().begin("c1")
    upload_worker._run(job, str(ws), service)
    assert reads == [1024]
    assert get_publish_state().snapshot()[0].status == STATUS_CANCELLED
    service.complete_upload.assert_not_called()
    service.delete_scene.assert_called_once_with(SCENE_ID)


def test_progress_reader_raises_a_non_oserror_cancel(tmp_path):
    path = tmp_path / "b"
    path.write_bytes(b"x" * 10)
    with open(path, "rb") as handle:
        reader = publish_api._ProgressReader(handle, 10, should_cancel=lambda: True)
        with pytest.raises(publish_api.UploadCancelled) as info:
            reader.read(4)
    assert not isinstance(info.value, OSError)


def test_failed_first_publish_deletes_its_draft_but_a_revision_never(tmp_path, monkeypatch):
    def storage_down(*args, **kwargs):
        raise PublishApiError("Upload failed (HTTP {status})", code="upload_failed",
                              status_code=500, params={"status": 500})

    monkeypatch.setattr(publish_api, "put_object", storage_down)
    job, ws = _job(tmp_path)
    service = _service()
    get_publish_state().begin("f1")
    upload_worker._run(job, str(ws), service)
    assert get_publish_state().snapshot()[0].status == STATUS_ERROR
    service.delete_scene.assert_called_once_with(SCENE_ID)

    revision_dir = tmp_path / "rev"
    revision_dir.mkdir()
    job, ws = _job(revision_dir, existing=SCENE_ID)
    service = _service()
    get_publish_state().begin("f2")
    upload_worker._run(job, str(ws), service)
    assert get_publish_state().snapshot()[0].status == STATUS_ERROR
    service.delete_scene.assert_not_called()


# -- 4. file load drops a stale outcome; undo restores a blanked record ----------------


def _fake_bpy(monkeypatch, scenes):
    wm = SimpleNamespace(mixar_web_publish_status="IDLE", mixar_web_publish_progress=0.0,
                         mixar_web_publish_scene="", windows=[])
    monkeypatch.setattr(pipeline, "bpy", SimpleNamespace(
        context=SimpleNamespace(window_manager=wm), data=SimpleNamespace(scenes=scenes)))


def _done(slug="loft"):
    return PublishResult(scene_id=SCENE_ID, slug=slug, revision=1,
                         share_url="https://scenes.mixar.app/s/" + slug)


def test_outcome_after_a_file_load_is_dropped(monkeypatch):
    props = _props()
    _fake_bpy(monkeypatch, {"Scene": SimpleNamespace(mixar_web_publish=props)})
    state = get_publish_state()
    state.begin("l1", "Scene", "panel", token=pipeline._load_generation)
    pipeline.on_load_pre()  # the user opened another file mid-upload
    state.set_result(_done())
    assert pipeline._mirror() is None
    assert props.slug == "" and props.published_scene_id == ""


def test_outcome_on_the_same_file_is_applied(monkeypatch):
    props = _props()
    _fake_bpy(monkeypatch, {"Scene": SimpleNamespace(mixar_web_publish=props)})
    state = get_publish_state()
    state.begin("l2", "Scene", "panel", token=pipeline._load_generation)
    state.set_result(_done())
    pipeline._mirror()
    assert (props.slug, props.published_scene_id) == ("loft", SCENE_ID)


def test_undo_restores_a_blanked_record_until_unpublish_or_load(monkeypatch):
    props = _props()
    _fake_bpy(monkeypatch, {"Scene": SimpleNamespace(mixar_web_publish=props)})
    state = get_publish_state()
    state.begin("u1", "Scene", "panel", token=pipeline._load_generation)
    state.set_result(_done())
    pipeline._mirror()

    props.published_scene_id = props.slug = props.share_url = ""  # undo_post
    pipeline.on_undo_redo()
    assert (props.published_scene_id, props.slug, props.share_url) == \
        (SCENE_ID, "loft", "https://scenes.mixar.app/s/loft")

    props.slug = "edited"  # a record that is not blank is never overwritten
    pipeline.on_undo_redo()
    assert props.slug == "edited"

    pipeline.clear_publication(props)  # unpublish
    pipeline.on_undo_redo()
    assert props.published_scene_id == ""

    state.begin("u2", "Scene", "panel", token=pipeline._load_generation)
    state.set_result(_done())
    pipeline._mirror()
    pipeline.on_load_pre()
    props.published_scene_id = ""
    pipeline.on_undo_redo()
    assert props.published_scene_id == ""


def test_ensure_handlers_registers_each_handler_once(monkeypatch):
    import sys

    from mixar.modules.web_publish.core import registration

    handlers = SimpleNamespace(load_pre=[], undo_post=[], redo_post=[])
    monkeypatch.setitem(sys.modules, "bpy", SimpleNamespace(app=SimpleNamespace(
        handlers=handlers)))
    registration.ensure_handlers()
    registration.ensure_handlers()
    assert handlers.load_pre == [pipeline.on_load_pre]
    assert handlers.undo_post == [pipeline.on_undo_redo]
    assert handlers.redo_post == [pipeline.on_undo_redo]
