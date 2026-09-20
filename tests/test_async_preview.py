# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Lifecycle of the agent's asynchronous preview render (core/preview_render.py).

Runs outside Blender with ``bpy`` mocked; the native job and the pixel proof
are exercised in the built app through the QA harness.
"""

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHAT_ROOT = ROOT / "src/scripts/mixar/modules/space_mixie_chat"
KEY = "a" * 32
OTHER = "b" * 32


def _scene():
    return SimpleNamespace(
        camera=object(),
        mixie_session_id="sess-1",
        cycles=SimpleNamespace(samples=64, device="GPU"),
        eevee=SimpleNamespace(taa_render_samples=64),
        render=SimpleNamespace(
            engine="CYCLES", resolution_x=1200, resolution_y=900,
            resolution_percentage=80, use_lock_interface=False,
            image_settings=SimpleNamespace(file_format="JPEG"),
        ),
    )


@pytest.fixture
def preview(monkeypatch):
    handlers_mod = sys.modules.get("bpy.app.handlers")
    if handlers_mod is not None:
        monkeypatch.setattr(handlers_mod, "persistent", lambda f: f, raising=False)
    spec = importlib.util.spec_from_file_location(
        "mixar.modules.space_mixie_chat.core.preview_render_under_test",
        CHAT_ROOT / "core/preview_render.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fake = MagicMock(name="bpy")
    fake.app.background = False
    fake.app.is_job_running.return_value = False
    fake.app.driver_namespace = {}
    for name in ("render_complete", "render_cancel", "depsgraph_update_post", "load_pre"):
        setattr(fake.app.handlers, name, [])
    fake.context.scene = _scene()
    fake.context.window = object()
    fake.context.preferences.view.render_display_type = "WINDOW"
    fake.ops.render.render.return_value = {"RUNNING_MODAL"}
    monkeypatch.setattr(module, "bpy", fake)
    return module


def _pixels(preview, data=b"pixels"):
    preview.bpy.data.images.get.return_value = SimpleNamespace(
        has_data=True, save_render=lambda path, scene: Path(path).write_bytes(data)
    )


def test_start_is_native_async_idempotent_and_reports_the_job(preview):
    ctx = preview.bpy.context
    first = preview.start(ctx, KEY)
    assert first["status"] == "running"
    assert first["job_id"] == KEY and first["scene_session"] == "sess-1"
    render = first["render"]
    assert (render["engine"], render["device"], render["samples"]) == ("CYCLES", "GPU", 32)
    assert (render["width"], render["height"]) == (768, 576)
    assert render["elapsed_seconds"] is None
    preview.bpy.app.is_job_running.return_value = True
    assert preview.start(ctx, KEY)["status"] == "running"  # idempotent, no restart
    assert preview.start(ctx, OTHER) == {
        "job_id": OTHER, "status": "busy", "error": "another_render_running"}
    preview.bpy.ops.render.render.assert_called_once_with("INVOKE_DEFAULT", write_still=False)
    assert ctx.preferences.view.render_display_type == "WINDOW"
    assert ctx.scene.render.use_lock_interface is False
    assert ctx.scene.render.resolution_percentage == 100
    assert ctx.scene.render.image_settings.file_format == "PNG"


def test_a_foreign_render_job_makes_start_busy(preview):
    preview.bpy.app.is_job_running.return_value = True
    assert preview.start(preview.bpy.context, KEY)["status"] == "busy"
    preview.bpy.ops.render.render.assert_not_called()


def test_invalid_key_is_refused_without_echoing_paths(preview):
    result = preview.start(preview.bpy.context, "/Users/private/x.blend")
    assert result["status"] == "failed" and result["error"] == "invalid_job_id"
    assert "/Users" not in result["job_id"] or len(result["job_id"]) <= 64
    preview.bpy.ops.render.render.assert_not_called()


def test_render_callback_only_schedules_main_loop_work(preview):
    preview.start(preview.bpy.context, KEY)
    preview.bpy.reset_mock()
    preview._complete(None)
    preview.bpy.app.timers.register.assert_called_once()
    preview.bpy.context.view_layer.update.assert_not_called()
    preview.bpy.data.images.get.assert_not_called()
    assert preview._job["finishing"]


def test_poll_is_cheap(preview):
    preview.start(preview.bpy.context, KEY)
    preview.bpy.reset_mock()
    assert preview.poll(KEY)["status"] == "running"
    preview.bpy.context.view_layer.update.assert_not_called()
    assert "view_layer.update" not in _poll_source()


def _poll_source():
    src = (CHAT_ROOT / "core/preview_render.py").read_text()
    return src[src.index("def poll("):src.index("def _apply_settings(")]


@pytest.mark.parametrize("completed", [True, False])
def test_done_pixels_survive_edits_but_cancelled_pixels_do_not(preview, completed):
    preview.start(preview.bpy.context, KEY)
    preview._changed(None, SimpleNamespace(mode="VIEWPORT", updates=[object()]))
    scene = preview.bpy.context.scene
    scene.cycles.samples = 48  # the user's own change during the job wins
    _pixels(preview)
    preview._finish(KEY, completed)
    result = preview.poll(KEY)
    assert result["status"] == ("done" if completed else "cancelled")
    assert result["scene_session"] == "sess-1"
    assert isinstance(result["render"]["elapsed_seconds"], float)
    if completed:
        assert result["scene_advanced"] is True
        assert result["image_url"].startswith("data:image/png;base64,")
        preview._changed(None, SimpleNamespace(mode="VIEWPORT", updates=[object()]))
        assert preview.poll(KEY)["image_url"] == result["image_url"]
    else:
        assert "image_url" not in result
        preview.bpy.data.images.get.assert_not_called()
    assert (scene.render.resolution_x, scene.render.resolution_y,
            scene.render.resolution_percentage, scene.cycles.samples) == (1200, 900, 80, 48)
    assert scene.render.image_settings.file_format == "JPEG"
    assert preview._job is None
    assert not preview.bpy.app.handlers.render_complete
    assert not preview.bpy.app.handlers.render_cancel


def test_unchanged_scene_is_not_reported_as_advanced(preview):
    preview.start(preview.bpy.context, KEY)
    _pixels(preview)
    preview._finish(KEY, True)
    assert preview.poll(KEY)["scene_advanced"] is False


def test_render_graph_updates_do_not_invalidate_preview(preview):
    preview._changed(None, SimpleNamespace(mode="RENDER", updates=[object()]))
    preview._changed(None, SimpleNamespace(mode="VIEWPORT", updates=[]))
    assert preview._revision == 0


def test_finalize_waits_for_native_teardown(preview):
    preview.start(preview.bpy.context, KEY)
    preview.bpy.app.is_job_running.return_value = True
    assert preview._finish(KEY, True) == 0.1
    preview.bpy.data.images.get.assert_not_called()
    assert preview._job is not None


def test_lost_callback_recovers_settings_without_restarting(preview, monkeypatch):
    preview.start(preview.bpy.context, KEY)
    monkeypatch.setattr(
        preview.time, "monotonic",
        lambda: preview._job["started_at"] + 3 if preview._job else 100.0,
    )
    result = preview.poll(KEY)
    assert result["status"] == "lost" and "image_url" not in result
    assert preview.bpy.context.scene.render.resolution_x == 1200
    preview.bpy.ops.render.render.assert_called_once()
    # The key is now terminal: START never re-runs it.
    assert preview.start(preview.bpy.context, KEY)["status"] == "lost"
    preview.bpy.ops.render.render.assert_called_once()


def test_image_failure_is_path_free_and_restores_settings(preview):
    preview.start(preview.bpy.context, KEY)
    preview.bpy.data.images.get.side_effect = RuntimeError("/Users/private/secret.blend")
    preview._finish(KEY, True)
    result = preview.poll(KEY)
    assert result["status"] == "failed" and result["error"] == "preview_image_unavailable"
    assert "/Users" not in str(result)
    assert preview.bpy.context.scene.render.resolution_x == 1200


def test_png_over_four_megabytes_is_refused(preview):
    preview.start(preview.bpy.context, KEY)
    _pixels(preview, b"x" * (preview.MAX_PNG_BYTES + 1))
    preview._finish(KEY, True)
    result = preview.poll(KEY)
    assert result["status"] == "failed" and result["error"] == "image_too_large"
    assert "image_url" not in result


def test_headless_and_failed_invoke_have_no_blocking_fallback(preview):
    preview.bpy.app.background = True
    result = preview.start(preview.bpy.context, KEY)
    assert result["status"] == "failed" and result["error"] == "camera_and_window_required"
    preview.bpy.ops.render.render.assert_not_called()
    preview.bpy.app.background = False
    preview.bpy.ops.render.render.return_value = {"CANCELLED"}
    result = preview.start(preview.bpy.context, OTHER)
    assert result["status"] == "failed" and result["error"] == "async_render_unavailable"
    preview.bpy.ops.render.render.assert_called_once_with("INVOKE_DEFAULT", write_still=False)
    assert preview.bpy.context.scene.render.resolution_x == 1200
    assert preview.bpy.context.preferences.view.render_display_type == "WINDOW"


def test_missing_camera_fails_without_touching_settings(preview):
    preview.bpy.context.scene.camera = None
    result = preview.start(preview.bpy.context, KEY)
    assert result["error"] == "camera_and_window_required"
    assert preview.bpy.context.scene.render.resolution_x == 1200


def test_eevee_samples_are_capped_and_missing_attributes_are_tolerated(preview):
    scene = preview.bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    result = preview.start(preview.bpy.context, KEY)
    assert scene.eevee.taa_render_samples == 16
    assert result["render"]["device"] == "engine_default"
    assert result["render"]["samples"] == 16
    assert scene.cycles.samples == 64
    preview._before_load(None)
    del scene.eevee
    assert preview.start(preview.bpy.context, OTHER)["status"] == "running"


def test_results_are_bounded_to_the_four_most_recent_keys(preview):
    keys = [chr(ord("a") + i) * 32 for i in range(6)]
    for key in keys:
        preview.start(preview.bpy.context, key)
        _pixels(preview)
        preview._finish(key, True)
    assert list(preview._records) == keys[2:]
    assert preview.poll(keys[0])["status"] == "lost"
    assert preview.bpy.app.driver_namespace[preview.RESULTS_NS] is preview._records


def test_reload_discards_old_scene_results_and_handlers(preview):
    preview.start(preview.bpy.context, KEY)
    preview._before_load(None)
    assert preview.poll(KEY)["status"] == "lost"
    assert preview._job is None
    assert not preview.bpy.app.handlers.render_complete


def test_sandbox_preserves_exact_callbacks_but_removes_impostors(monkeypatch):
    from mixar.modules.space_mixie_chat.core import executor_handlers, preview_render

    handlers = SimpleNamespace(render_complete=[], render_cancel=[],
                               depsgraph_update_post=[], load_pre=[])
    monkeypatch.setattr(executor_handlers, "bpy",
                        SimpleNamespace(app=SimpleNamespace(handlers=handlers)))
    executor = executor_handlers.HandlerCleanupMixin()
    snapshot = executor._snapshot_handlers()

    def impostor(*args):
        pass

    impostor.__name__ = preview_render._complete.__name__
    impostor.__module__ = preview_render._complete.__module__
    handlers.render_complete.extend([preview_render._complete, impostor])
    handlers.render_cancel.append(preview_render._cancelled)
    handlers.depsgraph_update_post.append(preview_render._changed)
    handlers.load_pre.append(preview_render._before_load)
    executor._cleanup_handlers(snapshot)
    assert handlers.render_complete == [preview_render._complete]
    assert handlers.render_cancel == [preview_render._cancelled]
    assert handlers.depsgraph_update_post == [preview_render._changed]
    assert handlers.load_pre == [preview_render._before_load]


def test_script_executor_inherits_the_handler_cleanup():
    src = (CHAT_ROOT / "core/executor.py").read_text()
    assert "class ScriptExecutor(HandlerCleanupMixin)" in src
    assert "_HANDLER_NAMES" not in src
    assert "agent_final_render" not in src


def test_native_render_stop_sets_the_pipeline_cancellation_flag():
    source = (ROOT / "src/source/blender/editors/interface/templates/"
              "interface_template_running_jobs.cc").read_text()
    block = source.split("if (WM_jobs_test(wm, &scene, WM_JOB_TYPE_RENDER)) {", 1)[1]
    block = block.split("icon = ICON_SCENE;", 1)[0]
    assert "G.is_break = true;" in block
    assert "WM_jobs_stop_all_from_owner(CTX_wm_manager(&C), &scene);" in block
    # Upstream's own helper is left alone; only the RENDER branch changes.
    assert source.count("G.is_break = true;") == 1
