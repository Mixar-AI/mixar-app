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

import bpy
from bpy.app.handlers import persistent

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

SPLAT_GN_MODIFIER = "KIRI_3DGS_Render_GN"
_ENABLE_MODE = "Enable Camera Updates"

_VIEW_BASE = 2    # Socket_2..17
_PROJ_BASE = 18   # Socket_18..33

# True between render_init and render_complete/render_cancel.
_rendering = False


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
    """Lock the interface on every scene that already contains splats.

    Files saved before this guard existed carry splat scenes WITHOUT
    use_lock_interface; rendering those with a live viewport is the
    mesh_calc_modifiers crash. Import-time covers new worlds; this covers
    every pre-existing file on load.
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
