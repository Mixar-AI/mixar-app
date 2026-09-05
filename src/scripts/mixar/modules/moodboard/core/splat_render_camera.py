# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Feed the render camera to KIRI splat objects during renders.

KIRI 3DGS Render draws splats two ways:

* interactively, via its proxy's GPU shader (viewport only);
* in real renders (F12 / animation), via the splat mesh's
  ``KIRI_3DGS_Render_GN`` geometry nodes, which build camera-facing quads
  from view/projection matrices stored in modifier sockets.

KIRI only ever fills those sockets from the 3D **viewport** (via short
`bpy.app.timers`, which do not fire inside a blocking animation render), so a
plain Blender render — including Director shot videos — comes out black or
smeared with stale matrices. This module owns the render-side half: handlers
push the **scene camera's** matrices into every enabled splat's sockets for
each rendered frame.

Socket layout (KIRI v4.1.5 ``sna_update_camera_single_time_9EF18``):
view matrix in Socket_2..17 and projection in Socket_18..33, both written
column-major (socket = base + col*4 + row); render width/height in
Socket_34/35. Frozen against the vendored addon — re-verify on KIRI updates.

Pushes happen ONLY while a render is in progress (``render_init`` →
``render_complete``/``render_cancel``): the splat mesh is eye-hidden behind
the proxy in the viewport, and re-tagging 500k-point geometry nodes on every
interactive frame-change (Director scrubbing) would be wasted work.
"""

import importlib

import bpy
from bpy.app.handlers import persistent

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

SPLAT_GN_MODIFIER = "KIRI_3DGS_Render_GN"
_ENABLE_MODE = "Enable Camera Updates"

# KIRI's viewport renderer is process-local: these caches, GPU textures, and
# its SpaceView3D draw handler are deliberately not Blender datablocks.  The
# proxy Empty *is* saved (including its packed ``gaussian_data`` ID property),
# so every .blend load must reconstruct that runtime after KIRI has registered.
# Function names are frozen against the vendored KIRI v4.1.5, just like the
# operator/socket contract used by world_labs_importer and this module.
_KIRI_ADDON_MODULE = "kiri_3dgs_render"
_KIRI_CLEANUP_FN = "sna_clean_up_scene_5F1F1"
_KIRI_SHADER_FN = "sna_shader_system_A4AED"
_KIRI_TEXTURE_FN = "sna_texture_creation_FD1B2"
_KIRI_VIEWPORT_FN = "sna_viewport_render_A3941"
_KIRI_RUNTIME_ATTRS = (
    "gaussian_draw_handle",
    "gaussian_object_cache",
    "gaussian_texture",
    "gaussian_quad_shader",
)

_RESTORE_FIRST_DELAY_S = 1.0
_RESTORE_RETRY_DELAY_S = 1.0
_RESTORE_MAX_ATTEMPTS = 8
_restore_attempts = 0

_VIEW_BASE = 2    # Socket_2..17
_PROJ_BASE = 18   # Socket_18..33

# True between render_init and render_complete/render_cancel.
_rendering = False


def _saved_splat_proxies() -> list:
    """Return saved KIRI proxy Empties without reading their large byte blobs."""
    try:
        return [
            obj for obj in bpy.data.objects
            if bool(obj.get("is_gaussian_splat", False))
            and int(obj.get("gaussian_count", 0) or 0) > 0
        ]
    except Exception:  # noqa: BLE001 - bpy.data can be restricted at startup
        return []


def _has_kiri_runtime() -> bool:
    """Whether process-local KIRI state survived from the previously open file."""
    return any(hasattr(bpy, name) for name in _KIRI_RUNTIME_ATTRS)


def _ready_kiri_module():
    """Return the registered vendored KIRI module, or None while it starts."""
    try:
        import addon_utils

        _enabled, loaded = addon_utils.check(_KIRI_ADDON_MODULE)
        if not loaded:
            return None
        module = importlib.import_module(_KIRI_ADDON_MODULE)
        required = (
            _KIRI_CLEANUP_FN,
            _KIRI_SHADER_FN,
            _KIRI_TEXTURE_FN,
            _KIRI_VIEWPORT_FN,
        )
        if not all(callable(getattr(module, name, None)) for name in required):
            return None
        return module
    except Exception:  # noqa: BLE001 - addon enable is intentionally deferred
        return None


def _show_source_point_clouds(proxies: list) -> int:
    """Unhide saved source meshes if GPU restoration ultimately cannot run."""
    source_ids = {
        str(proxy.get("source_mesh_uuid", "") or "") for proxy in proxies
    }
    source_ids.discard("")
    if not source_ids:
        return 0

    shown = 0
    for obj in bpy.data.objects:
        try:
            if str(obj.get("gaussian_source_uuid", "") or "") not in source_ids:
                continue
            obj.hide_viewport = False
            obj.hide_set(False)
            shown += 1
        except Exception:  # noqa: BLE001 - object may not be in the active view layer
            continue
    return shown


def _retry_or_fallback(reason: str, proxies: list):
    """Timer return helper: retry transient startup, then reveal source data."""
    if _restore_attempts < _RESTORE_MAX_ATTEMPTS:
        logger.debug(
            "[SplatRender] viewport restore attempt %d/%d deferred: %s",
            _restore_attempts,
            _RESTORE_MAX_ATTEMPTS,
            reason,
        )
        return _RESTORE_RETRY_DELAY_S

    shown = _show_source_point_clouds(proxies)
    logger.warning(
        "[SplatRender] could not restore KIRI viewport after %d attempts (%s); "
        "revealed %d source point-cloud object(s) instead",
        _restore_attempts,
        reason,
        shown,
    )
    return None


def restore_splat_viewport():
    """Timer callback rebuilding KIRI's non-persistent viewport runtime.

    A file load invalidates object pointers held in ``bpy.gaussian_object_cache``
    even when Mixar stays open, and a full application restart removes all GPU
    state.  Clear either form of stale runtime first, then let KIRI reconstruct
    its cache from the proxy Empties' saved ``gaussian_data`` properties.
    """
    global _restore_attempts

    proxies = _saved_splat_proxies()
    if not proxies and not _has_kiri_runtime():
        return None

    _restore_attempts += 1
    kiri = _ready_kiri_module()
    if kiri is None:
        return _retry_or_fallback("KIRI addon is not registered yet", proxies)

    try:
        getattr(kiri, _KIRI_CLEANUP_FN)(False)
        if not proxies:
            logger.debug("[SplatRender] cleared stale KIRI runtime for splat-free file")
            return None

        getattr(kiri, _KIRI_SHADER_FN)()
        getattr(kiri, _KIRI_TEXTURE_FN)()
        getattr(kiri, _KIRI_VIEWPORT_FN)()

        cache = getattr(bpy, "gaussian_object_cache", {})
        missing = [proxy.name for proxy in proxies if proxy.name not in cache]
        if missing:
            raise RuntimeError(f"proxy cache missing {', '.join(missing[:3])}")
        if not hasattr(bpy, "gaussian_draw_handle"):
            raise RuntimeError("viewport draw handler was not created")

        logger.info(
            "[SplatRender] restored %d saved splat proxy/proxies after file load",
            len(proxies),
        )
        return None
    except Exception as exc:  # noqa: BLE001 - GPU context may not be ready yet
        return _retry_or_fallback(str(exc), proxies)


def schedule_splat_viewport_restore() -> None:
    """Schedule one delayed restore for the current file, replacing stale work."""
    global _restore_attempts

    # Background renders use the saved geometry-nodes splat, not KIRI's
    # SpaceView3D GPU proxy, and may have no drawable GPU context at all.
    if bool(getattr(bpy.app, "background", False)):
        return
    if not _saved_splat_proxies() and not _has_kiri_runtime():
        return

    _restore_attempts = 0
    try:
        if bpy.app.timers.is_registered(restore_splat_viewport):
            bpy.app.timers.unregister(restore_splat_viewport)
        bpy.app.timers.register(
            restore_splat_viewport,
            first_interval=_RESTORE_FIRST_DELAY_S,
        )
    except Exception:  # noqa: BLE001 - restricted context during early startup
        logger.debug("[SplatRender] could not schedule viewport restore", exc_info=True)


def cancel_splat_viewport_restore() -> None:
    """Cancel a pending restore when the Mixar UI module unregisters."""
    try:
        if bpy.app.timers.is_registered(restore_splat_viewport):
            bpy.app.timers.unregister(restore_splat_viewport)
    except Exception:  # noqa: BLE001 - full interpreter shutdown
        pass


def scene_has_splats(scene) -> bool:
    """True when any mesh in *scene* carries the KIRI splat GN modifier."""
    return any(
        obj.type == 'MESH' and SPLAT_GN_MODIFIER in obj.modifiers
        for obj in scene.objects
    )


def enable_render_updates(objects) -> None:
    """Mark splat meshes for camera-driven updates (KIRI + our handlers).

    Safe no-op for non-splat objects or when the KIRI addon is disabled
    (the property group then doesn't exist).
    """
    for obj in objects:
        if getattr(obj, "type", None) != "MESH":
            continue
        if SPLAT_GN_MODIFIER not in getattr(obj, "modifiers", {}):
            continue
        props = getattr(obj, "sna_dgs_object_properties", None)
        if props is None:
            continue
        try:
            props.update_mode = _ENABLE_MODE
            props.cam_update = True
            # KIRI's enum/bool update callbacks act on the ACTIVE object (and
            # the current 3D view), which ours may not be — mirror their two
            # object-side effects explicitly: the update flag, and the GN
            # display mode (Socket_50: 0 = camera updates, 1 = disabled,
            # 2 = point cloud).
            obj["update_rot_to_cam"] = True
            obj.modifiers[SPLAT_GN_MODIFIER]["Socket_50"] = 0
            # KIRI "HQ Mode (Blended Alpha)": ordered alpha via the Sorter GN.
            # Under the default DITHERED/hashed transparency 500k overlapping
            # soft quads render as milky noise; BLENDED + back-to-front
            # sorting is the addon's own quality path, and it keeps the
            # sorter disabled unless the material is BLENDED.
            sorter = obj.modifiers.get("KIRI_3DGS_Sorter_GN")
            if sorter is not None:
                sorter.show_viewport = True
                sorter.show_render = True
            mat = bpy.data.materials.get("KIRI_3DGS_Render_Material")
            if mat is not None:
                mat.surface_render_method = "BLENDED"
        except Exception as e:  # noqa: BLE001 - enum identifiers changed?
            logger.warning("[SplatRender] enable failed on %s: %s", obj.name, e)
    # Renders of splat scenes MUST lock the interface: the per-frame camera
    # pushes below mutate original IDs from the render job while a live
    # viewport would concurrently evaluate the 500k-point GN for drawing —
    # that race crashed in mesh_calc_modifiers (Director shot render,
    # 2026-08-10). This is Blender's documented requirement for mutating
    # scene data from frame handlers during renders, and it must be set
    # BEFORE the render job starts, so it is a property of the splat scene.
    try:
        scene = bpy.context.scene
        if scene is not None and not scene.render.use_lock_interface:
            scene.render.use_lock_interface = True
            logger.info("[SplatRender] enabled Lock Interface for splat scene %s",
                        scene.name)
    except Exception:  # noqa: BLE001 - no context scene (headless edge)
        pass


def _splat_objects(scene):
    for obj in scene.objects:
        if obj.type != "MESH" or SPLAT_GN_MODIFIER not in obj.modifiers:
            continue
        props = getattr(obj, "sna_dgs_object_properties", None)
        if props is not None and props.update_mode == _ENABLE_MODE:
            yield obj


def _projection_matrix(cam, width, height, scale_x=1.0, scale_y=1.0):
    """Blender-equivalent camera projection matrix, no depsgraph needed.

    Port of BKE_camera_params_compute_viewplane + the frustum matrix, for
    the render handlers that receive no depsgraph. Small deviations only
    affect splat quad footprints (visual), never stability.
    """
    from mathutils import Matrix

    sensor_fit = cam.sensor_fit
    if sensor_fit == "AUTO":
        horizontal = (scale_x * width) >= (scale_y * height)
    else:
        horizontal = sensor_fit == "HORIZONTAL"
    sensor = cam.sensor_height if sensor_fit == "VERTICAL" else cam.sensor_width

    clip_start, clip_end = cam.clip_start, cam.clip_end
    is_ortho = cam.type == "ORTHO"
    if is_ortho:
        pixsize = cam.ortho_scale
        clip_start = max(clip_start, 1e-4)
    else:
        pixsize = (sensor * clip_start) / max(cam.lens, 1e-4)

    viewfac = width if horizontal else (scale_y / scale_x) * height
    pixsize /= viewfac

    xmax = 0.5 * width * pixsize
    ymax = 0.5 * height * (scale_y / scale_x) * pixsize
    xmin, ymin = -xmax, -ymax
    dx = cam.shift_x * viewfac * pixsize
    dy = cam.shift_y * viewfac * pixsize
    xmin += dx; xmax += dx; ymin += dy; ymax += dy

    m = Matrix.Identity(4)
    if is_ortho:
        m[0][0] = 2.0 / (xmax - xmin)
        m[1][1] = 2.0 / (ymax - ymin)
        m[2][2] = -2.0 / (clip_end - clip_start)
        m[0][3] = -(xmax + xmin) / (xmax - xmin)
        m[1][3] = -(ymax + ymin) / (ymax - ymin)
        m[2][3] = -(clip_end + clip_start) / (clip_end - clip_start)
    else:
        m[0][0] = 2.0 * clip_start / (xmax - xmin)
        m[1][1] = 2.0 * clip_start / (ymax - ymin)
        m[0][2] = (xmax + xmin) / (xmax - xmin)
        m[1][2] = (ymax + ymin) / (ymax - ymin)
        m[2][2] = -(clip_end + clip_start) / (clip_end - clip_start)
        m[2][3] = -2.0 * clip_end * clip_start / (clip_end - clip_start)
        m[3][2] = -1.0
        m[3][3] = 0.0
    return m


def push_camera_to_splats(scene, depsgraph=None) -> int:
    """Write the scene camera's matrices into every enabled splat. Returns count."""
    camera = scene.camera
    if camera is None:
        return 0
    splats = list(_splat_objects(scene))
    if not splats:
        return 0

    render = scene.render
    scale = render.resolution_percentage / 100.0
    width = max(1, int(render.resolution_x * scale))
    height = max(1, int(render.resolution_y * scale))
    view = camera.matrix_world.inverted()
    if depsgraph is not None:
        # frame_change_pre hands us the render depsgraph — evaluated camera.
        proj = camera.evaluated_get(depsgraph).calc_matrix_camera(
            depsgraph, x=width, y=height,
            scale_x=render.pixel_aspect_x, scale_y=render.pixel_aspect_y,
        )
    else:
        # render_init / render_pre have NO depsgraph, and fetching one via
        # bpy.context.evaluated_depsgraph_get() mid-render is itself a
        # crash risk — compute the projection from camera data directly.
        proj = _projection_matrix(
            camera.data, width, height,
            render.pixel_aspect_x, render.pixel_aspect_y,
        )

    for obj in splats:
        mod = obj.modifiers[SPLAT_GN_MODIFIER]
        for col in range(4):
            for row in range(4):
                mod[f"Socket_{_VIEW_BASE + col * 4 + row}"] = view[row][col]
                mod[f"Socket_{_PROJ_BASE + col * 4 + row}"] = proj[row][col]
        mod["Socket_34"] = float(width)
        mod["Socket_35"] = float(height)
        obj.update_tag(refresh={"DATA"})
    return len(splats)


@persistent
def on_load_post(_filepath=None):
    """Restore saved splats and lock their scenes after every file load.

    Files saved before this guard existed carry splat scenes WITHOUT
    use_lock_interface; rendering those with a live viewport is the
    mesh_calc_modifiers crash. Import-time covers new worlds; this covers
    every pre-existing file on load. The visible KIRI proxy also owns a
    process-local GPU runtime, so schedule its rebuild after the UI and the
    deferred KIRI addon registration are ready.
    """
    try:
        for sc in bpy.data.scenes:
            if sc.render.use_lock_interface:
                continue
            for obj in sc.objects:
                if obj.type == "MESH" and SPLAT_GN_MODIFIER in obj.modifiers:
                    sc.render.use_lock_interface = True
                    logger.info(
                        "[SplatRender] Lock Interface enabled for splat scene %s",
                        sc.name,
                    )
                    break
    except Exception:  # noqa: BLE001 - never break file load
        logger.debug("[SplatRender] load-post lock sweep failed", exc_info=True)
    schedule_splat_viewport_restore()


@persistent
def on_render_init(scene, *_args):
    global _rendering
    _rendering = True
    n = push_camera_to_splats(scene)
    if n:
        logger.info("[SplatRender] render camera pushed to %d splat(s)", n)


@persistent
def on_render_done(_scene, *_args):
    global _rendering
    _rendering = False


@persistent
def on_render_pre(scene, *_args):
    # Fires before each rendered frame — covers single-frame F12 renders and
    # re-asserts the first animation frame.
    push_camera_to_splats(scene)


@persistent
def on_frame_change_pre(scene, depsgraph=None):
    # Animation renders step frames through here; the depsgraph evaluates the
    # updated sockets right after, so each frame gets its own camera pose.
    if _rendering:
        push_camera_to_splats(scene, depsgraph)
