# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene-level mirror PropertyGroups for the queue UIList.

The canonical job state lives in ``FeatureQueue`` (Python singleton).
These PropertyGroups are a read-only mirror that the queue manager
refreshes via a listener so Blender's ``UIList`` can render the queue.
"""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import PropertyGroup

from mixar.modules.common.job_queue.constants import (
    FEATURE_HUNYUAN_PART,
    FEATURE_HUNYUAN_RAPID,
    FEATURE_HUNYUAN_UV,
    FEATURE_IMAGE_TO_3D_PRO,
    FEATURE_IMAGEGEN,
    FEATURE_LOOKDEV360,
    FEATURE_MATGEN,
    FEATURE_MESH_SEGMENT,
    FEATURE_MODEL_3D,
    FEATURE_RETOPOLOGY,
    FEATURE_SCENE_GEN_HP,
    FEATURE_SCENE_GEN_LP,
    FEATURE_SCENE_RECON,
)
from mixar.modules.common.job_queue.core.queue_manager import get_queue
from mixar.modules.common.job_queue.ui.queue_selection import on_active_index_changed


class MixieQueueItemPG(PropertyGroup):
    job_id: StringProperty(name="Job ID", default="")
    label: StringProperty(name="Label", default="")
    state: StringProperty(name="State", default="")
    substate_text: StringProperty(name="Substate", default="")
    error: StringProperty(name="Error", default="")
    user_message: StringProperty(name="User Message", default="")


class MixieFeatureQueuePG(PropertyGroup):
    items: CollectionProperty(type=MixieQueueItemPG)
    active_index: IntProperty(default=0, update=on_active_index_changed)


class MixieQueuesPG(PropertyGroup):
    image_to_3d_pro: PointerProperty(type=MixieFeatureQueuePG)
    retopology: PointerProperty(type=MixieFeatureQueuePG)
    scene_gen_hp: PointerProperty(type=MixieFeatureQueuePG)
    scene_gen_lp: PointerProperty(type=MixieFeatureQueuePG)
    hunyuan_rapid: PointerProperty(type=MixieFeatureQueuePG)
    hunyuan_part: PointerProperty(type=MixieFeatureQueuePG)
    hunyuan_uv: PointerProperty(type=MixieFeatureQueuePG)
    model_3d: PointerProperty(type=MixieFeatureQueuePG)
    imagegen: PointerProperty(type=MixieFeatureQueuePG)
    lookdev360: PointerProperty(type=MixieFeatureQueuePG)
    matgen: PointerProperty(type=MixieFeatureQueuePG)
    mesh_segment: PointerProperty(type=MixieFeatureQueuePG)
    scene_recon: PointerProperty(type=MixieFeatureQueuePG)


class MixieQueueUIPG(PropertyGroup):
    image_to_3d_pro_expanded: BoolProperty(
        name="Image to 3D Queue Expanded",
        description="Show / hide the image-to-3d Pro generation queue",
        default=True,
    )
    retopology_expanded: BoolProperty(
        name="Retopology Queue Expanded",
        description="Show / hide the retopology generation queue",
        default=True,
    )
    scene_gen_hp_expanded: BoolProperty(
        name="Scene Gen HP Queue Expanded",
        description="Show / hide the scene gen HP generation queue",
        default=True,
    )
    scene_gen_lp_expanded: BoolProperty(
        name="Scene Gen LP Queue Expanded",
        description="Show / hide the scene gen LP retopology queue",
        default=True,
    )
    hunyuan_rapid_expanded: BoolProperty(
        name="Hunyuan Rapid Queue Expanded",
        description="Show / hide the Hunyuan Rapid generation queue",
        default=True,
    )
    hunyuan_part_expanded: BoolProperty(
        name="Hunyuan Part Queue Expanded",
        description="Show / hide the Hunyuan Part generation queue",
        default=True,
    )
    hunyuan_uv_expanded: BoolProperty(
        name="Hunyuan UV Queue Expanded",
        description="Show / hide the Hunyuan UV generation queue",
        default=True,
    )
    model_3d_expanded: BoolProperty(
        name="Model 3D Queue Expanded",
        description="Show / hide the Image to 3D Basic generation queue",
        default=True,
    )
    imagegen_expanded: BoolProperty(
        name="Image Generation Queue Expanded",
        description="Show / hide the image generation queue",
        default=True,
    )
    lookdev360_expanded: BoolProperty(
        name="Lookdev360 Queue Expanded",
        description="Show / hide the Lookdev360 PBR generation queue",
        default=True,
    )
    matgen_expanded: BoolProperty(
        name="MatGen Queue Expanded",
        description="Show / hide the material generation queue",
        default=True,
    )
    mesh_segment_expanded: BoolProperty(
        name="Mesh Segmentation Queue Expanded",
        description="Show / hide the mesh segmentation queue",
        default=True,
    )
    scene_recon_expanded: BoolProperty(
        name="Scene Reconstruction Queue Expanded",
        description="Show / hide the scene reconstruction queue",
        default=True,
    )


classes = (
    MixieQueueItemPG,
    MixieFeatureQueuePG,
    MixieQueuesPG,
    MixieQueueUIPG,
)


# ---------------------------------------------------------------------------
# Mirror sync — registered as a queue listener so the UIList stays current.
# ---------------------------------------------------------------------------

_FEATURE_TO_ATTR = {
    FEATURE_IMAGE_TO_3D_PRO: "image_to_3d_pro",
    FEATURE_RETOPOLOGY: "retopology",
    FEATURE_SCENE_GEN_HP: "scene_gen_hp",
    FEATURE_SCENE_GEN_LP: "scene_gen_lp",
    FEATURE_HUNYUAN_RAPID: "hunyuan_rapid",
    FEATURE_HUNYUAN_PART: "hunyuan_part",
    FEATURE_HUNYUAN_UV: "hunyuan_uv",
    FEATURE_MODEL_3D: "model_3d",
    FEATURE_IMAGEGEN: "imagegen",
    FEATURE_LOOKDEV360: "lookdev360",
    FEATURE_MATGEN: "matgen",
    FEATURE_MESH_SEGMENT: "mesh_segment",
    FEATURE_SCENE_RECON: "scene_recon",
}


def _sync_mirror(queue) -> None:
    """Listener: rewrite the scene-side PropertyGroup mirror from a snapshot."""
    import mixar.modules.common.job_queue.ui.queue_selection as _sel_mod

    attr = _FEATURE_TO_ATTR.get(queue.feature_key)
    if attr is None:
        return
    try:
        scene = bpy.context.scene
    except Exception:
        return
    if scene is None or not hasattr(scene, "mixie_queues"):
        return

    pg = getattr(scene.mixie_queues, attr, None)
    if pg is None:
        return

    # Suppress selection callback while rebuilding the mirror
    _sel_mod._suppress_selection = True
    try:
        snapshot = queue.snapshot()
        pg.items.clear()
        for job in snapshot:
            item = pg.items.add()
            item.job_id = job.id
            item.label = job.label
            item.state = job.state.value if hasattr(job.state, "value") else str(job.state)
            item.substate_text = job.substate_text()
            item.error = job.error
            item.user_message = job.user_message
        if pg.active_index >= len(pg.items):
            pg.active_index = max(0, len(pg.items) - 1)
    finally:
        _sel_mod._suppress_selection = False


def _attach_listeners() -> None:
    """Attach _sync_mirror to every known feature queue (idempotent)."""
    from mixar.modules.common.job_queue.ui.queue_selection import (
        _ATTR_TO_FEATURE,
    )

    for feat, attr in _FEATURE_TO_ATTR.items():
        _ATTR_TO_FEATURE[attr] = feat
        try:
            get_queue(feat).add_listener(_sync_mirror)
        except Exception:
            pass


def register():
    from bpy.utils import register_class
    for cls in classes:
        try:
            register_class(cls)
        except ValueError:
            pass

    if not hasattr(bpy.types.Scene, "mixie_queues"):
        bpy.types.Scene.mixie_queues = PointerProperty(type=MixieQueuesPG)
    if not hasattr(bpy.types.Scene, "mixie_queue_ui"):
        bpy.types.Scene.mixie_queue_ui = PointerProperty(type=MixieQueueUIPG)

    _attach_listeners()


def unregister():
    from bpy.utils import unregister_class

    for attr in ("mixie_queue_ui", "mixie_queues"):
        try:
            delattr(bpy.types.Scene, attr)
        except AttributeError:
            pass

    for cls in reversed(classes):
        try:
            unregister_class(cls)
        except (RuntimeError, ValueError):
            pass
