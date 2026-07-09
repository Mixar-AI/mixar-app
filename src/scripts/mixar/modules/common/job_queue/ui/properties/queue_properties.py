# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene-level mirror PropertyGroup for the unified queue UIList.

Canonical job state lives in ``FeatureQueue`` (Python singleton).  This
mirror is a read-only projection that the queue manager refreshes via
per-feature listeners so Blender's ``UIList`` can render every job
across every feature as a single flat list, with a filter chip for
All / Active / Done / Failed.
"""

import time

import bpy
from bpy.props import (
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import PropertyGroup

from mixar.modules.common.job_queue.core.job import TERMINAL_STATES
from mixar.modules.common.job_queue.core.queue_manager import all_queues, get_queue
from mixar.modules.common.job_queue.ui.queue_selection import on_active_index_changed


FILTER_ITEMS = (
    ('ALL', "All", "Show every job"),
    ('ACTIVE', "Active", "Show pending or running jobs"),
    ('DONE', "Done", "Show successfully completed jobs"),
    ('FAILED', "Failed", "Show failed or cancelled jobs"),
)


class MixieQueueItemPG(PropertyGroup):
    job_id: StringProperty(name="Job ID", default="")
    feature_key: StringProperty(name="Feature Key", default="")
    label: StringProperty(name="Label", default="")
    state: StringProperty(name="State", default="")
    substate_text: StringProperty(name="Substate", default="")
    error: StringProperty(name="Error", default="")
    user_message: StringProperty(name="User Message", default="")
    created_at: FloatProperty(name="Created At", default=0.0)
    finished_at: FloatProperty(name="Finished At", default=0.0)


class MixieUnifiedQueuePG(PropertyGroup):
    items: CollectionProperty(type=MixieQueueItemPG)
    active_index: IntProperty(default=0, update=on_active_index_changed)
    filter_mode: EnumProperty(
        name="Filter",
        items=FILTER_ITEMS,
        default='ALL',
    )


classes = (
    MixieQueueItemPG,
    MixieUnifiedQueuePG,
)


# ---------------------------------------------------------------------------
# Mirror sync — one listener attached to every FeatureQueue; each tick
# rebuilds the unified list from all queues.
# ---------------------------------------------------------------------------


def _sync_mirror(_queue) -> None:
    """Rebuild the unified scene-side mirror from every FeatureQueue snapshot."""
    import mixar.modules.common.job_queue.ui.queue_selection as _sel_mod

    try:
        scene = bpy.context.scene
    except Exception:
        return
    if scene is None or not hasattr(scene, "mixie_queue"):
        return

    pg = scene.mixie_queue

    # Selected job identity, so we can preserve selection across rebuild.
    prev_key = ""
    if 0 <= pg.active_index < len(pg.items):
        prev_key = pg.items[pg.active_index].job_id

    _sel_mod._suppress_selection = True
    try:
        # Collect every job, newest first.
        rows = []
        for q in all_queues():
            for job in q.snapshot():
                rows.append((q.feature_key, job))
        rows.sort(key=lambda r: getattr(r[1], "created_at", 0.0), reverse=True)

        pg.items.clear()
        new_index = -1
        now = time.monotonic()
        for i, (feature_key, job) in enumerate(rows):
            # Stamp finished_at the first time we sync a terminal job so
            # the row's elapsed clock freezes at the completion instant.
            # Uses monotonic to match Job.created_at — mixing clocks would
            # break elapsed = finished_at - created_at.
            if job.state in TERMINAL_STATES and not job.finished_at:
                job.finished_at = now

            item = pg.items.add()
            item.job_id = job.id
            item.feature_key = feature_key
            item.label = job.label
            item.state = (
                job.state.value if hasattr(job.state, "value") else str(job.state)
            )
            item.substate_text = job.substate_text()
            item.error = job.error
            item.user_message = job.user_message
            item.created_at = getattr(job, "created_at", 0.0)
            item.finished_at = getattr(job, "finished_at", 0.0)
            if prev_key and item.job_id == prev_key:
                new_index = i

        if new_index >= 0:
            pg.active_index = new_index
        elif pg.active_index >= len(pg.items):
            pg.active_index = max(0, len(pg.items) - 1)
    finally:
        _sel_mod._suppress_selection = False

    # Whenever the queue changes, make sure the blink pump is running if a
    # RUNNING_* job exists. The pump self-terminates when the queue idles.
    try:
        from mixar.modules.common.job_queue.ui import queue_status_icons
        queue_status_icons.start_blink_if_needed()
    except Exception:
        pass


def _attach_listeners() -> None:
    """Attach the unified _sync_mirror to every known feature queue."""
    from mixar.modules.common.job_queue.constants import (
        FEATURE_BRUSH_GEN,
        FEATURE_HUNYUAN_PART,
        FEATURE_HUNYUAN_RAPID,
        FEATURE_HUNYUAN_UV,
        FEATURE_IMAGE_TO_3D_PRO,
        FEATURE_IMAGEGEN,
        FEATURE_LOOKDEV,
        FEATURE_LOOKDEV360,
        FEATURE_MATGEN,
        FEATURE_MESH_SEGMENT,
        FEATURE_MODEL_3D,
        FEATURE_RETOPOLOGY,
        FEATURE_SCENE_GEN,
        FEATURE_SCENE_GEN_HP,
        FEATURE_SCENE_GEN_LP,
        FEATURE_SCENE_RECON,
    )

    _FEATURES = (
        FEATURE_IMAGE_TO_3D_PRO, FEATURE_RETOPOLOGY, FEATURE_SCENE_GEN_HP,
        FEATURE_SCENE_GEN_LP, FEATURE_HUNYUAN_RAPID, FEATURE_HUNYUAN_PART,
        FEATURE_HUNYUAN_UV, FEATURE_MODEL_3D, FEATURE_IMAGEGEN,
        FEATURE_LOOKDEV, FEATURE_LOOKDEV360, FEATURE_MATGEN, FEATURE_BRUSH_GEN,
        FEATURE_MESH_SEGMENT, FEATURE_SCENE_GEN, FEATURE_SCENE_RECON,
    )
    for feat in _FEATURES:
        try:
            get_queue(feat).add_listener(_sync_mirror)
        except Exception:
            pass


def _force_list_text_sel_white():
    """Make the highlighted UIList row's text white.

    The fork's factory theme (and any user prefs saved from it) ships a
    dark ``wcol_list_item.text_sel``, which renders the selected queue
    row's text near-black on the green selection bar. The factory default
    is fixed in userdef_default_theme.c; this runtime pass covers builds
    predating that fix and previously saved preferences. Runs on a timer:
    theme writes must stay off the draw path.
    """
    import bpy
    try:
        theme = bpy.context.preferences.themes[0]
        theme.user_interface.wcol_list_item.text_sel = (1.0, 1.0, 1.0)
    except Exception:
        pass
    return None


def register():
    from bpy.utils import register_class
    for cls in classes:
        try:
            register_class(cls)
        except ValueError:
            pass

    bpy.app.timers.register(_force_list_text_sel_white, first_interval=0.5)

    if not hasattr(bpy.types.Scene, "mixie_queue"):
        bpy.types.Scene.mixie_queue = PointerProperty(type=MixieUnifiedQueuePG)

    _attach_listeners()

    # Deferred preview-icon load — mutates bpy.data via bpy.utils.previews,
    # so it MUST run on a timer tick, never inside a draw_item callback.
    try:
        from mixar.modules.common.job_queue.ui import queue_status_icons
        queue_status_icons.register()
    except Exception:
        pass


def unregister():
    from bpy.utils import unregister_class

    try:
        from mixar.modules.common.job_queue.ui import queue_status_icons
        queue_status_icons.unregister()
    except Exception:
        pass

    try:
        delattr(bpy.types.Scene, "mixie_queue")
    except AttributeError:
        pass

    for cls in reversed(classes):
        try:
            unregister_class(cls)
        except (RuntimeError, ValueError):
            pass
