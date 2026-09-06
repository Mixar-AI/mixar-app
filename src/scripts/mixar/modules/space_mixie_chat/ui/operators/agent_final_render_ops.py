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

Outcome reporting: the backend cannot see the background render's outcome on
its own (its turn already ended), so every completion, user cancellation, and
lost completion (stale-job self-heal, no Render Result to save) is reported
back as a ``render.final_render_result`` notification, echoing the ``job_key``
the kickoff embedded (session/turn identity). Reporting is best-effort and
carries NO local paths — the file only ever lives on this machine.

This must live in unsandboxed addon code: the completion handlers and the
deferred finalize timer outlive the sandboxed script that started the job.

Thread model (docs/render-job-contract.md): the render never blocks the
agent. Scripts keep running on the main thread and the user keeps working
while the job renders its own depsgraph — Lock Interface is left exactly as
the user has it, and the sandbox executor has no render gate (3.4.2 shipped
both and was reverted in 3.4.4: the lock froze every UI handler and the hold
failed every turn whose render outlived 20 s). The one render-thread rule
that stands: ``render_complete`` / ``render_cancel`` fire ON the job thread
(``RE_RenderFrame``), so the handlers below only register a one-shot timer
and ``_finalize`` does all ``bpy.data`` work on the main thread.

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

Lighting cap (#1270): energies above the backend-passed ``light_caps`` are
reduced FOR THE RENDER ONLY (originals saved + restored in
``_restore_settings``). Only pathological values are touched — an
LLM-authored 1e6 W point light or a 500 W/m^2 sun — legitimate bright
scenes pass untouched.
"""

from mixar.config.logging_config import get_logger
import json
import tempfile
import time

import bpy

logger = get_logger(__name__)

_RESULTS_NS = "mixie_agent_final_render"

# One render job at a time. {"scene_name", "path", "label", "saved", "handlers_on"}
_job = None


def _parse_light_caps(light_caps_json):
    """The backend-passed caps {sun_energy, light_energy, emission_strength,
    world_strength}; sane defaults when absent (old backend)."""
    try:
        caps = json.loads(light_caps_json or "{}")
        if isinstance(caps, dict):
            return caps
    except Exception:
        pass
    return {}


def _cap_lights(scene, caps):
    """Cap scene light energies + emission/world strengths for the render.

    Returns (originals, capped_names). Mirrors the backend's synchronous
    fallback template ``tools/scripts/render/render_scene.py`` (_cap_lights).
    """
    capped = []
    originals = {}
    try:
        sun_max = float(caps.get("sun_energy", 50.0))
        light_max = float(caps.get("light_energy", 10000.0))
        for light in bpy.data.lights:
            if light is None or light.type not in ("SUN", "POINT", "SPOT", "AREA"):
                continue
            limit = sun_max if light.type == "SUN" else light_max
            energy = getattr(light, "energy", 0.0) or 0.0
            if energy > limit > 0:
                originals["light:" + light.name] = energy
                light.energy = limit
                capped.append(light.name)
    except Exception:
        logger.exception("agent_final_render: light energy cap failed")
    try:
        emission_max = float(caps.get("emission_strength", 1000.0))
        for mat in bpy.data.materials:
            if not mat or not mat.use_nodes or not mat.node_tree:
                continue
            for node in mat.node_tree.nodes:
                if node.type != "EMISSION":
                    continue
                try:
                    strength_val = float(node.inputs["Strength"].default_value)
                except Exception:
                    continue
                if strength_val > emission_max > 0:
                    originals["emission:" + mat.name + ":" + node.name] = strength_val
                    node.inputs["Strength"].default_value = emission_max
                    capped.append(mat.name + " (emission)")
    except Exception:
        logger.exception("agent_final_render: emission cap failed")
    try:
        world_max = float(caps.get("world_strength", 50.0))
        world = scene.world
        if world is not None and world.use_nodes and world.node_tree:
            for node in world.node_tree.nodes:
                if node.type != "BACKGROUND":
                    continue
                try:
                    strength_val = float(node.inputs["Strength"].default_value)
                except Exception:
                    continue
                if strength_val > world_max > 0:
                    originals["world:" + node.name] = strength_val
                    node.inputs["Strength"].default_value = world_max
                    capped.append("world background")
    except Exception:
        logger.exception("agent_final_render: world strength cap failed")
    if capped:
        logger.warning(
            "agent_final_render: capped %d light source(s) for the render "
            "(restored afterwards): %s", len(capped), ", ".join(capped[:10]),
        )
    return originals, capped


def _restore_lights(scene, originals):
    for key, value in originals.items():
        try:
            kind, _, rest = key.partition(":")
            if kind == "light":
                light = bpy.data.lights.get(rest)
                if light is not None:
                    light.energy = value
            elif kind == "emission":
                mat_name, _, node_name = rest.rpartition(":")
                mat = bpy.data.materials.get(mat_name)
                node = (
                    mat.node_tree.nodes.get(node_name)
                    if mat is not None and mat.use_nodes and mat.node_tree
                    else None
                )
                if node is not None:
                    node.inputs["Strength"].default_value = value
            elif kind == "world":
                world = scene.world
                node = (
                    world.node_tree.nodes.get(rest)
                    if world is not None and world.use_nodes and world.node_tree
                    else None
                )
                if node is not None:
                    node.inputs["Strength"].default_value = value
        except Exception:
            pass


def _results() -> dict:
    return bpy.app.driver_namespace.setdefault(_RESULTS_NS, {})


def _get_ws_client():
    """The global JSON-RPC WS client (lazy import; None when disconnected)."""
    try:
        from mixar.modules.space_mixie_chat.core.jsonrpc_client import (
            get_jsonrpc_client,
        )

        return get_jsonrpc_client()
    except Exception:
        return None


def _report_result(job, status, error=None, moodboard_name=None,
                   duration_seconds=None):
    """Tell the backend how one background render ended (best-effort).

    The backend's turn already ended when the render does, so this
    notification is the ONLY server-side evidence of the outcome — it lands
    as a Langfuse observation + Loki event there. Echoes the job_key (the
    session/turn identity the backend pinned at kickoff). Local paths never
    leave this machine.
    """
    try:
        if not job or not job.get("job_key"):
            return  # job started before reporting existed — nothing to echo
        from mixar.modules.space_mixie_chat.constants import JSONRPCMethod

        client = _get_ws_client()
        if client is None:
            logger.info(
                "agent_final_render: no WS client — outcome (%s) not reported",
                status,
            )
            return
        payload = {
            "job_key": job["job_key"],
            "status": status,
            "engine": job.get("engine") or "",
        }
        if duration_seconds is not None:
            payload["duration_seconds"] = round(float(duration_seconds), 1)
        if moodboard_name:
            payload["moodboard_image_name"] = moodboard_name
        if error:
            payload["error"] = str(error)[:500]
        sent = client.send_notification(JSONRPCMethod.RENDER_FINAL_RESULT, payload)
        logger.info(
            "agent_final_render: outcome reported (%s, sent=%s)",
            status, sent,
        )
    except Exception:
        logger.exception("agent_final_render: outcome reporting failed")


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


def _apply_settings(scene, engine, samples, resolution_percentage, device, path,
                    light_caps=None):
    """Apply the requested render settings + the lighting cap; return
    (saved, device_note, light_originals, lights_capped).

    ``saved`` holds every value we changed, for restore on complete/cancel.
    ``light_originals`` holds the pre-cap energies (#1270) — restored by
    ``_restore_settings``.
    """
    saved = {
        "engine": scene.render.engine,
        "rp": scene.render.resolution_percentage,
        "fp": scene.render.filepath,
        "ff": scene.render.image_settings.file_format,
    }
    device_note = None
    # Lock Interface is deliberately left as the user has it. Forcing it on
    # (3.4.2) froze every UI handler for the whole render — the chat, the
    # bubble, the viewport — and gave the user no way to keep working while
    # the agent's render ran. The render evaluates its own depsgraph on the
    # job thread; a user's F12 runs unlocked by default for the same reason.
    light_originals, lights_capped = _cap_lights(scene, light_caps or {})

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
    return saved, device_note, light_originals, lights_capped


def _restore_settings(scene, saved):
    """Put back every value ``_apply_settings`` changed (complete AND cancel).

    Tolerates a ``saved`` dict persisted by the 3.4.2 operator, which carried
    a ``lock`` key: it is ignored — ``use_lock_interface`` belongs to the
    user and is never written here (docs/render-job-contract.md).
    """
    try:
        scene.render.engine = saved["engine"]
        scene.render.resolution_percentage = saved["rp"]
        scene.render.filepath = saved["fp"]
        scene.render.image_settings.file_format = saved["ff"]
    except Exception:
        logger.exception("agent_final_render: base settings restore failed")
    # #1270: the pre-cap light energies come back with everything else.
    try:
        _restore_lights(scene, saved.get("light_originals") or {})
    except Exception:
        logger.exception("agent_final_render: light cap restore failed")
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
    started_at = job.get("started_at") or 0.0
    duration = (time.time() - started_at) if started_at else None
    scene = bpy.data.scenes.get(job["scene_name"])
    try:
        if success and scene is not None:
            if _save_render_result(scene, job["path"]):
                name = _import_to_moodboard(scene, job["path"], job["label"])
                logger.info(
                    "agent_final_render: '%s' added to moodboard (%s)",
                    name, job["path"],
                )
                _report_result(
                    job, "done",
                    moodboard_name=name,
                    duration_seconds=duration,
                )
            else:
                logger.warning("agent_final_render: no Render Result to save")
                _report_result(
                    job, "error",
                    error="render produced no Render Result to save",
                    duration_seconds=duration,
                )
        elif not success:
            logger.info("agent_final_render: render canceled — settings restored")
            _report_result(job, "cancelled", duration_seconds=duration)
    except Exception:
        logger.exception("agent_final_render: finalize failed")
        _report_result(
            job, "error",
            error="finalize failed after the render job",
            duration_seconds=duration,
        )
    finally:
        if scene is not None:
            _restore_settings(scene, job["saved"])
        try:
            bpy.ops.mixie_chat.prune_render_cache(keep=200)
        except Exception:
            pass
    return None  # unregister the timer


def _on_render_complete(_scene, _depsgraph=None):
    # These handlers fire ON the render job thread (RE_RenderFrame), not the
    # main loop. Touching bpy.data here is the real render-thread crash class;
    # defer every bit of work (image save, moodboard mutation, settings
    # restore, redraws) to a main-thread timer tick.
    bpy.app.timers.register(lambda: _finalize(True), first_interval=0.1)


def _on_render_cancel(_scene, _depsgraph=None):
    # Same thread rule as _on_render_complete.
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
    # JSON dict of #1270 lighting caps from the backend (defaults when absent).
    light_caps_json: bpy.props.StringProperty(default="")

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
            # The previous job never fired its completion handlers — tell the
            # backend its outcome is lost, or its "started" state dangles
            # forever server-side.
            _report_result(
                _job, "lost",
                error="render completion was lost (handlers stripped or "
                      "Blender restarted); job state cleared",
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
            saved, device_note, _light_originals, _lights_capped = _apply_settings(
                scene, self.engine, self.samples,
                self.resolution_percentage, self.device, path,
                light_caps=_parse_light_caps(self.light_caps_json),
            )
        except Exception as e:
            return _fail("applying render settings failed: %s" % e)
        saved["light_originals"] = _light_originals

        _job = {
            "scene_name": scene.name,
            "path": path,
            "label": self.label,
            "saved": saved,
            "job_key": self.job_key,
            "engine": scene.render.engine,
            "started_at": time.time(),
            "lights_capped": _lights_capped,
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
                "lights_capped": _lights_capped,
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
