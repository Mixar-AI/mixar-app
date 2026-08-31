# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fire-and-forget FINAL render for the agent's `render_scene` tool.

The backend render lane kicks this off from a sandboxed script and ends its
turn immediately ("render started — it will appear on the moodboard"). The
render itself runs as Blender's normal interactive render job (INVOKE_DEFAULT,
same as F12) so the UI stays responsive and shows progress; when it finishes,
the ``render_complete`` handler saves the Render Result, imports it into the
moodboard (packed into the .blend), restores every render setting we touched,
and prunes the temp render cache. ``render_cancel`` restores settings too, so
a user-aborted render never leaves the scene reconfigured.

This must live in unsandboxed addon code: the completion handlers and the
deferred finalize timer outlive the sandboxed script that started the job.

Result contract (sandbox-readable, mirrors mixie_chat.render_scene):
    bpy.ops.mixie_chat.agent_final_render(engine=..., samples=...,
        resolution_percentage=..., device=..., label=..., job_key=K)
    res = bpy.app.driver_namespace["mixie_agent_final_render"].pop(K)
    # {"status": "started", "output_path": ..., "engine": ..., "device_note": ...}
    # {"status": "done", ...}   (blocking fallback path — moodboard already done)
    # {"status": "error", "error": "..."}

Settings application (engine/samples/resolution%/device incl. GPU preference
enabling) intentionally mirrors the backend's synchronous fallback template
``tools/scripts/render/render_scene.py`` — keep the two in sync.
"""

from mixar.config.logging_config import get_logger
import tempfile
import time

import bpy

logger = get_logger(__name__)

_RESULTS_NS = "mixie_agent_final_render"

# One render job at a time. {"scene_name", "path", "label", "saved", "handlers_on"}
_job = None


def _results() -> dict:
    return bpy.app.driver_namespace.setdefault(_RESULTS_NS, {})


def _tmp_render_path() -> str:
    # mixar_render_ prefix keeps these under the prune_render_cache cap.
    return (
        tempfile.gettempdir().rstrip("/\\")
        + "/"
        + "mixar_render_scene_%d.png" % int(time.time() * 1000)
    )


def _resolve_engine(requested: str):
    """Requested engine -> valid engine id, or None for 'keep current'."""
    req = (requested or "current").strip().lower()
    if req == "cycles":
        return "CYCLES"
    if req in ("eevee", "blender_eevee", "blender_eevee_next"):
        try:
            avail = list(
                bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items.keys()
            )
        except Exception:
            avail = []
        for cand in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
            if not avail or cand in avail:
                return cand
    return None


def _apply_settings(scene, engine, samples, resolution_percentage, device, path):
    """Apply the requested render settings; return (saved, device_note).

    ``saved`` holds every value we changed, for restore on complete/cancel.
    """
    saved = {
        "engine": scene.render.engine,
        "rp": scene.render.resolution_percentage,
        "fp": scene.render.filepath,
        "ff": scene.render.image_settings.file_format,
    }
    device_note = None

    target_engine = _resolve_engine(engine) or scene.render.engine
    scene.render.engine = target_engine

    if samples > 0:
        if target_engine == "CYCLES":
            saved["cycles_samples"] = scene.cycles.samples
            scene.cycles.samples = samples
        else:
            saved["eevee_samples"] = scene.eevee.taa_render_samples
            scene.eevee.taa_render_samples = samples

    dev = (device or "current").strip().upper()
    if target_engine == "CYCLES" and dev in ("GPU", "CPU"):
        saved["cycles_device"] = scene.cycles.device
        scene.cycles.device = dev
        if dev == "GPU":
            try:
                prefs = bpy.context.preferences.addons["cycles"].preferences
                saved["compute_type"] = prefs.compute_device_type
                picked = None
                for ctype in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
                    try:
                        prefs.compute_device_type = ctype
                    except Exception:
                        continue
                    try:
                        prefs.get_devices()
                    except Exception:
                        pass
                    gpus = [
                        d for d in getattr(prefs, "devices", [])
                        if getattr(d, "type", "CPU") != "CPU"
                    ]
                    if gpus:
                        for d in gpus:
                            d.use = True
                        picked = ctype
                        break
                if picked is None:
                    scene.cycles.device = "CPU"
                    device_note = "no GPU compute device found — rendering on CPU"
                else:
                    device_note = "GPU via %s" % picked
            except Exception as e:
                scene.cycles.device = "CPU"
                device_note = "GPU setup failed (%s) — rendering on CPU" % e

    if resolution_percentage > 0:
        scene.render.resolution_percentage = max(10, min(resolution_percentage, 400))

    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = path
    return saved, device_note


def _restore_settings(scene, saved):
    try:
        scene.render.engine = saved["engine"]
        scene.render.resolution_percentage = saved["rp"]
        scene.render.filepath = saved["fp"]
        scene.render.image_settings.file_format = saved["ff"]
    except Exception:
        logger.exception("agent_final_render: base settings restore failed")
    if "cycles_samples" in saved:
        try:
            scene.cycles.samples = saved["cycles_samples"]
        except Exception:
            pass
    if "eevee_samples" in saved:
        try:
            scene.eevee.taa_render_samples = saved["eevee_samples"]
        except Exception:
            pass
    if "cycles_device" in saved:
        try:
            scene.cycles.device = saved["cycles_device"]
        except Exception:
            pass
    if "compute_type" in saved:
        try:
            bpy.context.preferences.addons["cycles"].preferences.compute_device_type = (
                saved["compute_type"]
            )
        except Exception:
            pass


def _import_to_moodboard(scene, path, label):
    """Load the rendered file, pack it, and place it on the moodboard."""
    from mixar.modules.common.utils.image_utils import (
        add_image_to_moodboard,
        load_image_from_file,
    )

    img = load_image_from_file(path, "Render %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    try:
        add_image_to_moodboard(img, prompt=label or "Scene render")
    except Exception:
        # The helper adds the item before its final redraw loop — a late
        # context failure (e.g. no screen in this tick) is not a lost image.
        logger.exception("agent_final_render: moodboard placement hiccup")
    return img.name


def _save_render_result(scene, path) -> bool:
    """Save the 'Render Result' image to ``path``. True on success."""
    rr = bpy.data.images.get("Render Result")
    if rr is None:
        return False
    try:
        rr.save_render(path, scene=scene)
        return True
    except Exception:
        logger.exception("agent_final_render: save_render failed")
        return False


def _finalize(success: bool):
    """Deferred (timer) completion: save + import on success, restore always."""
    global _job
    job = _job
    _job = None
    _remove_handlers()
    if job is None:
        return None
    scene = bpy.data.scenes.get(job["scene_name"])
    try:
        if success and scene is not None:
            if _save_render_result(scene, job["path"]):
                name = _import_to_moodboard(scene, job["path"], job["label"])
                logger.info(
                    "agent_final_render: '%s' added to moodboard (%s)",
                    name, job["path"],
                )
            else:
                logger.warning("agent_final_render: no Render Result to save")
        elif not success:
            logger.info("agent_final_render: render canceled — settings restored")
    except Exception:
        logger.exception("agent_final_render: finalize failed")
    finally:
        if scene is not None:
            _restore_settings(scene, job["saved"])
        try:
            bpy.ops.mixie_chat.prune_render_cache(keep=200)
        except Exception:
            pass
    return None  # unregister the timer


def _on_render_complete(_scene, _depsgraph=None):
    # Handlers run at a delicate point in the render pipeline — defer the real
    # work (image save, moodboard mutation, redraws) to a timer tick.
    bpy.app.timers.register(lambda: _finalize(True), first_interval=0.1)


def _on_render_cancel(_scene, _depsgraph=None):
    bpy.app.timers.register(lambda: _finalize(False), first_interval=0.1)


def _add_handlers():
    if _on_render_complete not in bpy.app.handlers.render_complete:
        bpy.app.handlers.render_complete.append(_on_render_complete)
    if _on_render_cancel not in bpy.app.handlers.render_cancel:
        bpy.app.handlers.render_cancel.append(_on_render_cancel)


def _remove_handlers():
    try:
        if _on_render_complete in bpy.app.handlers.render_complete:
            bpy.app.handlers.render_complete.remove(_on_render_complete)
        if _on_render_cancel in bpy.app.handlers.render_cancel:
            bpy.app.handlers.render_cancel.remove(_on_render_cancel)
    except Exception:
        pass


class MIXIE_CHAT_OT_agent_final_render(bpy.types.Operator):
    """Start a final engine render as a background job; on completion the
    image is imported into the moodboard and the settings are restored."""

    bl_idname = "mixie_chat.agent_final_render"
    bl_label = "Agent Final Render"
    bl_options = {"INTERNAL"}

    engine: bpy.props.StringProperty(default="current")
    samples: bpy.props.IntProperty(default=0, min=0, max=4096)
    resolution_percentage: bpy.props.IntProperty(default=0, min=0, max=400)
    device: bpy.props.StringProperty(default="current")
    label: bpy.props.StringProperty(default="")
    job_key: bpy.props.StringProperty()

    def execute(self, context):
        global _job
        if not self.job_key:
            self.report({"ERROR"}, "job_key required")
            return {"CANCELLED"}

        def _fail(msg: str):
            _results()[self.job_key] = {"status": "error", "error": msg}
            return {"FINISHED"}  # error travels in the result; the script decides

        if _job is not None:
            # Self-heal: if no render job is actually running, the previous
            # job's completion was lost (e.g. its handlers were stripped) —
            # restore that job's settings and proceed instead of wedging
            # every future render behind a phantom "in progress".
            stale = False
            try:
                stale = not bpy.app.is_job_running("RENDER")
            except Exception:
                pass
            if not stale:
                return _fail(
                    "a final render is already in progress — wait for it to finish"
                )
            logger.warning(
                "agent_final_render: clearing stale job state (no render running)"
            )
            old_scene = bpy.data.scenes.get(_job["scene_name"])
            if old_scene is not None:
                _restore_settings(old_scene, _job["saved"])
            _job = None
            _remove_handlers()

        scene = context.scene
        if scene.camera is None:
            return _fail(
                "no active camera (scene.camera is None) — create and frame a "
                "camera first"
            )

        path = _tmp_render_path()
        try:
            saved, device_note = _apply_settings(
                scene, self.engine, self.samples,
                self.resolution_percentage, self.device, path,
            )
        except Exception as e:
            return _fail("applying render settings failed: %s" % e)

        _job = {
            "scene_name": scene.name,
            "path": path,
            "label": self.label,
            "saved": saved,
        }
        _add_handlers()

        # Async path: the interactive render job (same machinery as F12) — UI
        # stays responsive, progress is visible, handlers fire on completion.
        try:
            win = context.window or next(
                iter(bpy.context.window_manager.windows), None
            )
            if win is None:
                raise RuntimeError("no window")
            with bpy.context.temp_override(window=win, scene=scene):
                ret = bpy.ops.render.render("INVOKE_DEFAULT", write_still=False)
            if "CANCELLED" in ret:
                raise RuntimeError("render job refused to start")
            _results()[self.job_key] = {
                "status": "started",
                "output_path": path,
                "engine": scene.render.engine,
                "resolution_percentage": scene.render.resolution_percentage,
                "device_note": device_note,
            }
            return {"FINISHED"}
        except Exception as e:
            logger.info(
                "agent_final_render: async start unavailable (%s) — "
                "falling back to blocking render", e,
            )

        # Blocking fallback (e.g. no window): render synchronously, finalize
        # inline. The handlers still fire, but _finalize is a no-op afterwards
        # because we clear _job here.
        try:
            bpy.ops.render.render(write_still=False)
            if not _save_render_result(scene, path):
                return _fail("render produced no Render Result")
            name = _import_to_moodboard(scene, path, self.label)
            _results()[self.job_key] = {
                "status": "done",
                "output_path": path,
                "engine": scene.render.engine,
                "resolution_percentage": scene.render.resolution_percentage,
                "moodboard_image_name": name,
                "device_note": device_note,
            }
            return {"FINISHED"}
        except Exception as e:
            return _fail("blocking render failed: %s" % e)
        finally:
            _job = None
            _remove_handlers()
            _restore_settings(scene, saved)
            try:
                bpy.ops.mixie_chat.prune_render_cache(keep=200)
            except Exception:
                pass


classes = (
    MIXIE_CHAT_OT_agent_final_render,
)
