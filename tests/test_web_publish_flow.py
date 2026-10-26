# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""PR #1372's web_publish reliability fixes, ported to the 5.2 structure:
claim semantics, presigned-URL redaction, 401 with a failed refresh,
thumbnail bytes, ``resolution_percentage`` restore and cancel at every
stage. Runs outside Blender.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests

from mixar.modules.web_publish.core import publish_api, upload_worker
from mixar.modules.web_publish.core.publish_api import PublishApiError, ScenePublishService
from mixar.modules.web_publish.core.publish_state import (
    STATUS_CANCELLED,
    STATUS_ERROR,
    STATUS_EXPORTING,
    PublishJob,
    PublishState,
    get_publish_state,
)

SIGNED = "https://bucket.s3.example.com/obj?X-Amz-Signature=SECRET"


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    from mixar.modules.web_publish.core import publish_state

    monkeypatch.setattr(publish_state, "_state", publish_state.PublishState())


def _job(glb_path="", existing=""):
    return PublishJob(title="T", description="", visibility="public", glb_path=str(glb_path),
                      thumbnail_path="", content_sha256="a" * 64,
                      existing_scene_id=existing, existing_slug="s" if existing else "")


def _plan():
    return {"id": "s1", "slug": "s", "revision": 1}, {"mode": "put", "url": SIGNED}


# -- 1. atomic claim before export, reused by the hand-off -------------------------


class TestClaim:
    def test_claim_starts_when_idle(self):
        state = PublishState()
        assert state.claim() is True and state.busy is True
        assert state.snapshot()[0].status == STATUS_EXPORTING

    def test_claim_refused_while_busy(self):
        state = PublishState()
        state.start()
        assert state.claim() is False
        assert state.snapshot()[0].status == STATUS_EXPORTING  # untouched

    def test_claim_allows_restart_after_terminal(self):
        state = PublishState()
        state.set_error("x")
        assert state.claim() is True

    def test_claimed_handoff_starts_worker_and_keeps_a_cancel(self):
        state = get_publish_state()
        assert state.claim("p", "Scene") is True
        state.request_cancel()  # e.g. requested while the export ran
        with patch.object(upload_worker.threading, "Thread") as thread_cls:
            assert upload_worker.spawn(_job(), "/tmp/mixar_web_publish_x", MagicMock()) is True
        assert thread_cls.return_value.start.called
        assert state.cancel_requested is True  # a re-claim would have wiped it

    def test_handoff_without_a_claim_reports_instead_of_staying_silent(self):
        state = get_publish_state()
        with patch.object(upload_worker.threading, "Thread") as thread_cls:
            assert upload_worker.spawn(_job(), "/tmp/mixar_web_publish_x", MagicMock()) is False
        assert not thread_cls.called
        progress, _ = state.snapshot()
        assert progress.status == STATUS_ERROR and "claim" in progress.error_text


# -- 6. cancel at every stage ----------------------------------------------------------


class TestWorkerCancelChecks:
    def test_cancel_before_first_request(self, tmp_path):
        glb = tmp_path / "scene.glb"
        glb.write_bytes(b"glTF-fake")
        state = get_publish_state()
        state.claim()
        state.request_cancel()
        service = MagicMock()
        upload_worker._run(_job(glb), str(tmp_path / "mixar_web_publish_a"), service)
        assert state.snapshot()[0].status == STATUS_CANCELLED
        service.init_publish.assert_not_called()

    def test_cancel_during_init_skips_single_put(self, tmp_path, monkeypatch):
        glb = tmp_path / "scene.glb"
        glb.write_bytes(b"glTF-fake")
        state = get_publish_state()
        state.claim()
        service = MagicMock()
        service.init_publish.side_effect = lambda body: (state.request_cancel(), _plan())[1]
        puts = []
        monkeypatch.setattr(publish_api, "put_object", lambda *a, **k: puts.append(a))
        upload_worker._run(_job(glb), str(tmp_path / "mixar_web_publish_b"), service)
        assert state.snapshot()[0].status == STATUS_CANCELLED and puts == []
        service.delete_scene.assert_called_once_with("s1")  # first publish: draft discarded

    def test_cancel_during_upload_skips_complete(self, tmp_path, monkeypatch):
        glb = tmp_path / "scene.glb"
        glb.write_bytes(b"glTF-fake")
        state = get_publish_state()
        state.claim()
        service = MagicMock()
        service.init_publish.return_value = _plan()
        monkeypatch.setattr(publish_api, "put_object", lambda *a, **k: state.request_cancel())
        upload_worker._run(_job(glb), str(tmp_path / "mixar_web_publish_c"), service)
        assert state.snapshot()[0].status == STATUS_CANCELLED
        service.complete_upload.assert_not_called()

    def test_retry_loop_honors_cancel(self, monkeypatch):
        state = PublishState()
        state.request_cancel()
        parts = []
        monkeypatch.setattr(publish_api, "put_part", lambda *a, **k: parts.append(a))
        with pytest.raises(upload_worker._Cancelled):
            upload_worker._put_part_with_retry(SIGNED, "unused", 0, 8, state, None, 1)
        assert parts == []


# -- 2. presigned URLs never reach a message or a log -----------------------------------


@pytest.mark.parametrize("call", ["put_object", "put_part"])
def test_storage_failures_hide_the_presigned_query(call, tmp_path, monkeypatch):
    target = tmp_path / "scene.glb"
    target.write_bytes(b"glTF-fake" * 2)
    logged = []
    monkeypatch.setattr(publish_api, "log_network_failure",
                        lambda logger, failure, context: logged.append(repr(failure)))
    error = requests.ConnectionError(
        "HTTPSConnectionPool(host='bucket.s3.example.com', port=443): Max retries exceeded "
        f"with url: /obj?X-Amz-Signature=SECRET (Caused by boom) {SIGNED}")
    with patch.object(publish_api.requests, "put", side_effect=error):
        with pytest.raises(PublishApiError) as info:
            if call == "put_object":
                publish_api.put_object(SIGNED, str(target), 18, "model/gltf-binary")
            else:
                publish_api.put_part(SIGNED, str(target), 0, 18)
    blob = " ".join([info.value.message, repr(info.value.params)] + logged)
    assert "SECRET" not in blob and "X-Amz-Signature" not in blob
    assert info.value.code == "network" and info.value.__cause__ is None
    assert logged  # still classified and logged, just redacted


# -- 3. 401 + failed refresh → "Sign-in expired", no stale retry ------------------------


def _http_client(monkeypatch, responses, refresh):
    from mixar.modules.common.api import client as client_module

    monkeypatch.setattr(client_module, "get_access_token", lambda: "stale")
    monkeypatch.setattr(client_module, "refresh_access_token", lambda: refresh)
    http = client_module.HTTPClient(base_url="https://api.example.com", retry_count=0)
    session = MagicMock()
    session.request.side_effect = responses
    http._session = session
    return http, session


def _response(status, body=None):
    response = MagicMock(status_code=status, ok=200 <= status < 300, headers={})
    response.json.return_value = body if body is not None else {}
    response.text = ""
    return response


def test_401_with_failed_refresh_raises_friendly_auth_error(monkeypatch):
    http, session = _http_client(monkeypatch, [_response(401)],
                                 {"success": False, "message": "No refresh token available"})
    with pytest.raises(PublishApiError) as info:
        ScenePublishService(http).init_publish({})
    assert session.request.call_count == 1  # no retry against the stale token
    assert info.value.code == "auth" and info.value.status_code == 401
    assert "Sign-in expired" in info.value.message


def test_401_with_successful_refresh_retries_request(monkeypatch):
    ok = _response(200, {"status": "success", "data": {"scene": {"id": "s"}, "upload": {}}})
    http, session = _http_client(monkeypatch, [_response(401), ok], {"success": True})
    assert ScenePublishService(http).init_publish({})[0] == {"id": "s"}
    assert session.request.call_count == 2


# -- 4. thumbnail body is bytes (a retry re-sends it) ------------------------------------


def test_upload_thumbnail_body_is_reusable_bytes(tmp_path):
    thumb = tmp_path / "thumb.png"
    thumb.write_bytes(b"png-bytes")
    client = MagicMock()
    client.post.return_value = SimpleNamespace(data={"status": "success", "data": {}})
    ScenePublishService(client).upload_thumbnail("8f14e45f-ceea-467a-9575-1a2b3c4d5e6f", str(thumb))
    assert client.post.call_args.kwargs["data"] == b"png-bytes"


# -- 5. resolution_percentage restored after the thumbnail --------------------------------


def test_thumbnail_restores_resolution_percentage(monkeypatch, tmp_path):
    from contextlib import nullcontext

    from mixar.modules.web_publish.core import thumbnail

    image = SimpleNamespace(media_type="IMAGE", file_format="OPEN_EXR",
                            color_mode="RGBA", color_depth="16")
    render = SimpleNamespace(resolution_x=1920, resolution_y=1080, resolution_percentage=50,
                             filepath="//out/", use_file_extension=True, image_settings=image)
    scene = SimpleNamespace(render=render)
    seen = {}

    def opengl(**kwargs):
        seen.update(pct=render.resolution_percentage, fmt=image.file_format)

    fake_bpy = SimpleNamespace(
        context=SimpleNamespace(window_manager=SimpleNamespace(mixar_window_resizing=False),
                                temp_override=lambda **k: nullcontext()),
        ops=SimpleNamespace(render=SimpleNamespace(opengl=opengl)),
    )
    monkeypatch.setattr(thumbnail, "bpy", fake_bpy)
    monkeypatch.setattr(thumbnail, "can_render_now", lambda: True)
    monkeypatch.setattr(thumbnail, "_view3d_target", lambda scene: ("w", "a", "r"))
    from mixar.modules.common.render_coordinator import core as render_coordinator
    monkeypatch.setattr(render_coordinator, "reserve", lambda owner: nullcontext())
    thumbnail.render_thumbnail(scene, str(tmp_path / "t.png"))
    assert seen == {"pct": 100, "fmt": "PNG"}
    assert (render.resolution_x, render.resolution_y, render.resolution_percentage) == \
        (1920, 1080, 50)
    assert (render.filepath, render.use_file_extension, image.file_format) == \
        ("//out/", True, "OPEN_EXR")


# -- backend deltas (scene_publish port) --------------------------------------------------


def test_revision_sends_scene_id_and_slug(tmp_path, monkeypatch):
    glb = tmp_path / "scene.glb"
    glb.write_bytes(b"glTF-fake")
    service = MagicMock()
    service.base_url = ""
    service.init_publish.return_value = ({"id": "s1", "slug": "s"}, {"mode": "dedup"})
    get_publish_state().claim()
    upload_worker._run(_job(glb, existing="s1"), str(tmp_path / "mixar_web_publish_d"), service)
    body = service.init_publish.call_args[0][0]
    assert body["scene_id"] == "s1" and body["slug"] == "s"


def test_moderation_refusal_reason_becomes_the_code():
    from mixar.modules.common.api.exceptions import AuthorizationError

    detail = {"detail": {"status": "failure", "message": "This title can't be published.",
                         "data": {"reason": "content_policy"}}}
    client = MagicMock()
    client.post.side_effect = AuthorizationError(message="x", status_code=403,
                                                 response_data=detail)
    with pytest.raises(PublishApiError) as info:
        ScenePublishService(client).init_publish({})
    assert info.value.code == "content_policy"
    assert info.value.params == {"message": "This title can't be published."}


# -- template-field collisions never kill the worker or keep the slot ----------------


def test_network_error_carrying_message_reports_and_releases_the_claim(tmp_path, monkeypatch):
    from mixar.modules.common.api.exceptions import ConnectionError as ApiConnectionError

    monkeypatch.setattr(publish_api, "log_network_failure", lambda *a, **k: None)
    glb = tmp_path / "scene.glb"
    glb.write_bytes(b"glTF-fake")
    client = MagicMock()
    client._base_url = "http://127.0.0.1:9"
    client.post.side_effect = ApiConnectionError("Failed to connect")
    state = get_publish_state()
    state.claim("n1")
    upload_worker._run(_job(glb), str(tmp_path / "mixar_web_publish_n"), ScenePublishService(client))
    progress, _ = state.snapshot()
    assert progress.status == STATUS_ERROR and state.busy is False
    assert "message" in progress.error_args  # the colliding field, formatted fine
    assert "(NET-" in progress.error_text
    from mixar.modules.web_publish.core import agent_api
    assert agent_api.publish_status("n1")["status"] == "failed"


def test_export_failure_reports_through_fail_and_releases(monkeypatch):
    from mixar.modules.web_publish.core import pipeline

    def explode(*args, **kwargs):
        raise RuntimeError("Exporter returned CANCELLED")

    monkeypatch.setattr(pipeline, "_signed_in", lambda: True)
    monkeypatch.setattr(pipeline, "ensure_timer", lambda: None)
    monkeypatch.setattr(pipeline, "_telemetry", lambda *a: None)
    monkeypatch.setattr(pipeline.glb_export, "visible_meshes", lambda scene: [object()])
    monkeypatch.setattr(pipeline.glb_export, "export_glb", explode)
    props = SimpleNamespace(title="", description="", visibility="public",
                            include_animation=True, published_scene_id="", slug="")
    context = SimpleNamespace(scene=SimpleNamespace(name="Loft", mixar_web_publish=props))
    outcome = pipeline.begin_publish(context)
    assert outcome == {"ok": False, "error": "{message}",
                       "error_args": {"message": "Exporter returned CANCELLED"}}
    progress, _ = get_publish_state().snapshot()
    assert progress.status == STATUS_ERROR and get_publish_state().busy is False
    assert progress.error_text == "Exporter returned CANCELLED"


class _Fatal(BaseException):
    pass


def test_unexpected_worker_crash_ends_failed_with_the_slot_free(tmp_path):
    glb = tmp_path / "scene.glb"
    glb.write_bytes(b"glTF-fake")
    service = MagicMock()
    service.init_publish.side_effect = _Fatal("boom")
    state = get_publish_state()
    state.claim("u1")
    ws = tmp_path / "mixar_web_publish_u"
    ws.mkdir()
    upload_worker._run(_job(glb), str(ws), service)
    progress, _ = state.snapshot()
    assert progress.status == STATUS_ERROR and state.busy is False
    assert progress.error_text == "Publish failed (_Fatal)"
    assert not ws.exists()
    assert state.claim("next") is True
