# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Render a NON-ACTIVE scene to a PNG, synchronously, for agent scripts.

Why this exists (ISSUE-012): agent verification renders must show the scene the
agent is AUTHORING in (an ``agentlane:*`` workspace), not the window's scene.
Inside the ScriptExecutor sandbox every capture path is dead for a pinned
non-window scene: ``bpy.ops.render.render`` no-ops on the GUI main thread,
``bpy.ops.render.opengl`` draws nothing there either, the window screenshot
shows the previously-drawn scene (the pin flips scene pointers WITHOUT a
redraw), and ``import gpu`` is not whitelisted — deliberately. So the GPU work
lives HERE, in unsandboxed addon code, exposed as one operator the sandboxed
script may call.

Mechanism — the same family the agent Scene Strip thumbnails use
(``view3d_agent_strip_draw.cc``: ``ED_view3d_draw_offscreen_simple`` with an
explicit scene): ``gpu.types.GPUOffScreen.draw_view3d(scene, ...)`` takes the
scene EXPLICITLY, so it renders the requested scene regardless of what the
window shows — no scene flip, no framebuffer read, immune to pin races by
construction.

Context handling: scripts execute from a ``bpy.app.timers`` tick
(``main_thread_executor``), where a GPU context is not guaranteed. The
operator first tries the draw directly (on macOS the window's GL context is
typically current on the main thread); if GPU state is unavailable it enqueues
the job and forces ONE synchronous redraw (``wm.redraw_timer``) so the service
draw-handler — a guaranteed-GPU moment, like the strip — completes the job
before the operator returns. Either way the call is synchronous for the
script.

Result contract (sandbox-readable, no new whitelisting):
    bpy.ops.mixie_chat.render_scene(scene_session=..., scene_name=...,
                                    width=W, height=H, job_key=K)
    res = bpy.app.driver_namespace["mixie_scene_render"].pop(K)
    # res = {"status": "done", "image_base64": ..., "width": W, "height": H}
    # or    {"status": "error", "error": "..."}
"""

from mixar.config.logging_config import get_logger
import base64
import struct
import zlib

import bpy

logger = get_logger(__name__)

_RESULTS_NS = "mixie_scene_render"

# Pending jobs for the draw-handler path: job_key -> spec dict.
_pending: dict = {}
_draw_handler = None


def _results() -> dict:
    return bpy.app.driver_namespace.setdefault(_RESULTS_NS, {})


def _resolve_scene(scene_session: str, scene_name: str):
    """Scene by ``mixie_session_id`` (authoritative — names can collide),
    falling back to name."""
    if scene_session:
        for s in bpy.data.scenes:
            sid = getattr(s, "mixie_session_id", "") or s.get("mixie_session_id", "")
            if sid == scene_session:
                return s
    if scene_name:
        return bpy.data.scenes.get(scene_name)
    return None


def encode_rgba_png(rgba: bytes, width: int, height: int, flip_vertical: bool = True) -> bytes:
    """Encode raw 8-bit RGBA rows as a PNG, in pure Python.

    ``rgba`` is ``width * height * 4`` bytes. A GPU framebuffer read is
    bottom-up (GL origin), so rows are flipped by default to PNG's top-down
    order. Uncompressed-filter PNG (filter byte 0 per row, zlib stream):
    what the throwaway ``bpy.data.images`` round trip used to produce, without
    the datablock.
    """
    row = width * 4
    expected = row * height
    if len(rgba) != expected:
        raise ValueError(f"expected {expected} RGBA bytes, got {len(rgba)}")
    rows = range(height - 1, -1, -1) if flip_vertical else range(height)
    raw = b"".join(b"\x00" + rgba[y * row:(y + 1) * row] for y in rows)

    def chunk(tag: bytes, payload: bytes) -> bytes:
        body = tag + payload
        return (struct.pack(">I", len(payload)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8-bit RGBA
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def _encode_buffer_png(buf, width: int, height: int) -> str:
    """UBYTE RGBA framebuffer -> base64 PNG.

    Pure Python on purpose. This runs from ``_service_pending`` — a VIEW_3D
    POST_PIXEL draw callback — on the deferred path, and the previous
    implementation created, saved and REMOVED a ``bpy.data.images`` datablock
    there. Mutating ``bpy.data`` inside a draw callback is the crash class this
    repo already documents for the queue-status icons (``queue_status_icons.py``)
    and forbids in CLAUDE.md; an ID free mid-draw tears down image buffers and
    GPU textures the draw manager may still be reading. No datablock, no
    temp file, no notifier: just bytes.
    """
    buf.dimensions = width * height * 4
    try:
        import numpy as np

        rgba = np.asarray(buf, dtype=np.uint8).tobytes()
    except Exception:
        rgba = bytes(bytearray(int(v) & 0xFF for v in buf))
    return base64.b64encode(encode_rgba_png(rgba, width, height)).decode("ascii")


def _draw_scene_offscreen(scene, width: int, height: int, v3d, region) -> str:
    """GL-draw ``scene`` through ITS camera into an offscreen buffer; return
    base64 PNG. Raises on failure (caller decides direct-vs-deferred).

    ``v3d``/``region`` supply draw settings (shading/overlays) — from the live
    draw context on the handler path, or borrowed from any open VIEW_3D on the
    direct path. The SCENE being drawn is the explicit argument; the borrowed
    space's own scene is irrelevant.
    """
    import gpu

    cam = scene.camera
    if cam is None:
        raise RuntimeError(f"scene '{scene.name}' has no camera")
    # HARD GUARD: drawing a scene whose depsgraph has never been evaluated
    # SEGFAULTS (confirmed 2026-07-03: probe on a same-tick-created scene
    # crashed the app; the strip only draws scenes "evaluated on the main-loop
    # refresh phase"). Use the TARGET scene's own depsgraph — never the active
    # scene's — and refuse cleanly when it isn't available yet: the caller
    # gets an error result (verification records INDETERMINATE), not a crash.
    deps = scene.view_layers[0].depsgraph
    if deps is None:
        raise RuntimeError(
            f"scene '{scene.name}' has no evaluated depsgraph yet — retry after "
            "the next main-loop refresh"
        )
    view_m = cam.matrix_world.inverted()
    proj_m = cam.calc_matrix_camera(deps, x=width, y=height)
    offscreen = gpu.types.GPUOffScreen(width, height)
    try:
        with offscreen.bind():
            fb = gpu.state.active_framebuffer_get()
            fb.clear(color=(0.18, 0.18, 0.18, 1.0))
        offscreen.draw_view3d(
            scene, scene.view_layers[0], v3d, region, view_m, proj_m,
            do_color_management=True,
        )
        with offscreen.bind():
            fb = gpu.state.active_framebuffer_get()
            buf = fb.read_color(0, 0, width, height, 4, 0, "UBYTE")
    finally:
        offscreen.free()
    return _encode_buffer_png(buf, width, height)


def _find_view3d():
    """Any open VIEW_3D space + WINDOW region (draw-settings donor)."""
    for w in bpy.context.window_manager.windows:
        for a in w.screen.areas:
            if a.type == "VIEW_3D":
                region = next((r for r in a.regions if r.type == "WINDOW"), None)
                if region is not None:
                    return a.spaces.active, region
    return None, None


def _service_pending():
    """Draw-handler: complete queued jobs inside a real draw (GPU guaranteed).
    Runs in whatever VIEW_3D is drawing; the target scene is explicit, so which
    viewport hosts the draw does not matter."""
    if not _pending:
        return
    v3d = bpy.context.space_data
    region = bpy.context.region
    for key in list(_pending.keys()):
        job = _pending.pop(key)
        try:
            scene = _resolve_scene(job["scene_session"], job["scene_name"])
            if scene is None:
                raise RuntimeError(
                    f"no scene for session '{job['scene_session']}' / name '{job['scene_name']}'"
                )
            b64 = _draw_scene_offscreen(scene, job["width"], job["height"], v3d, region)
            _results()[key] = {
                "status": "done", "image_base64": b64,
                "width": job["width"], "height": job["height"],
            }
        except Exception as e:  # job errors must never break the viewport draw
            logger.warning(f"scene render job {key} failed in draw handler: {e}")
            _results()[key] = {"status": "error", "error": str(e)}


def _ensure_draw_handler():
    global _draw_handler
    if _draw_handler is None:
        _draw_handler = bpy.types.SpaceView3D.draw_handler_add(
            _service_pending, (), "WINDOW", "POST_PIXEL"
        )


class MIXIE_CHAT_OT_render_scene(bpy.types.Operator):
    """Render a scene (by session id or name) through its camera to a base64
    PNG in ``bpy.app.driver_namespace['mixie_scene_render'][job_key]``.
    Synchronous; window-independent; renders NON-ACTIVE scenes."""

    bl_idname = "mixie_chat.render_scene"
    bl_label = "Render Scene Offscreen (agent)"
    bl_options = {"INTERNAL"}

    scene_session: bpy.props.StringProperty(default="")
    scene_name: bpy.props.StringProperty(default="")
    width: bpy.props.IntProperty(default=512, min=64, max=2048)
    height: bpy.props.IntProperty(default=384, min=64, max=2048)
    job_key: bpy.props.StringProperty()

    def execute(self, context):
        if not self.job_key:
            self.report({"ERROR"}, "job_key required")
            return {"CANCELLED"}

        def _fail(msg: str):
            _results()[self.job_key] = {"status": "error", "error": msg}
            return {"FINISHED"}  # error is in the result; the script decides

        scene = _resolve_scene(self.scene_session, self.scene_name)
        if scene is None:
            return _fail(
                f"no scene for session '{self.scene_session}' / name '{self.scene_name}'"
            )
        if scene.camera is None:
            return _fail(f"scene '{scene.name}' has no camera")

        # Path 1 — direct draw. Works when a GL context is current on the main
        # thread (typical on macOS even from a timer tick). Cheapest, and no
        # visible redraw of the user's window.
        v3d, region = _find_view3d()
        if v3d is not None:
            try:
                b64 = _draw_scene_offscreen(scene, self.width, self.height, v3d, region)
                _results()[self.job_key] = {
                    "status": "done", "image_base64": b64,
                    "width": self.width, "height": self.height,
                }
                return {"FINISHED"}
            except Exception as e:
                logger.debug(f"direct offscreen draw unavailable ({e}); deferring to draw handler")

        # Path 2 — deferred: queue the job and force ONE synchronous redraw so
        # the service draw-handler (guaranteed GPU context, same moment the
        # Scene Strip thumbnails render in) completes it before we return.
        _ensure_draw_handler()
        _pending[self.job_key] = {
            "scene_session": self.scene_session, "scene_name": self.scene_name,
            "width": self.width, "height": self.height,
        }
        try:
            win = context.window or next(iter(bpy.context.window_manager.windows), None)
            if win is None:
                raise RuntimeError("no window for redraw")
            with bpy.context.temp_override(window=win):
                bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
        except Exception as e:
            _pending.pop(self.job_key, None)
            return _fail(f"forced redraw failed: {e}")

        if self.job_key in _pending:  # no VIEW_3D drew (e.g. no 3D viewport open)
            _pending.pop(self.job_key, None)
            return _fail("no VIEW_3D redraw serviced the render job")
        return {"FINISHED"}


classes = (
    MIXIE_CHAT_OT_render_scene,
)
