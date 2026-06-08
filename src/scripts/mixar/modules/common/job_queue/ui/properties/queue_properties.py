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
    FEATURE_IMAGE_TO_3D_PRO,
    FEATURE_RETOPOLOGY,
    FEATURE_SCENE_GEN_HP,
    FEATURE_SCENE_GEN_LP,
)
from mixar.modules.common.job_queue.core.queue_manager import get_queue


class MixieQueueItemPG(PropertyGroup):
    job_id: StringProperty(name="Job ID", default="")
    label: StringProperty(name="Label", default="")
    state: StringProperty(name="State", default="")
    substate_text: StringProperty(name="Substate", default="")
    error: StringProperty(name="Error", default="")


class MixieFeatureQueuePG(PropertyGroup):
    items: CollectionProperty(type=MixieQueueItemPG)
    active_index: IntProperty(default=0)


class MixieQueuesPG(PropertyGroup):
    image_to_3d_pro: PointerProperty(type=MixieFeatureQueuePG)
    retopology: PointerProperty(type=MixieFeatureQueuePG)
    scene_gen_hp: PointerProperty(type=MixieFeatureQueuePG)
    scene_gen_lp: PointerProperty(type=MixieFeatureQueuePG)


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
}


def _sync_mirror(queue) -> None:
    """Listener: rewrite the scene-side PropertyGroup mirror from a snapshot."""
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

    snapshot = queue.snapshot()
    pg.items.clear()
    for job in snapshot:
        item = pg.items.add()
        item.job_id = job.id
        item.label = job.label
        item.state = job.state.value if hasattr(job.state, "value") else str(job.state)
        item.substate_text = job.substate_text()
        item.error = job.error
    if pg.active_index >= len(pg.items):
        pg.active_index = max(0, len(pg.items) - 1)


def _attach_listeners() -> None:
    """Attach _sync_mirror to every known feature queue (idempotent)."""
    for feat in _FEATURE_TO_ATTR.keys():
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
