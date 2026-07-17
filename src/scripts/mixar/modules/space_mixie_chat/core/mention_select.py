# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Viewport selection sync for '@' mentions in the Mixie Chat composer.

Accepting a mention (Enter/Tab/click on a dropdown row) fires the
`scene.mixie_chat_mention_accepted` update from C++
(mixie_chat_mention.cc), whose callback schedules `schedule_selection_sync`
here. The sync makes the 3D viewport selection mirror the assets currently
mentioned in the composer text:

  - object mention     -> the object plus its whole subtree
  - material mention   -> every scene object using that material
  - collection mention -> the collection's objects in this scene

The sync is ADDITIVE: it never deselects objects the user picked manually —
"change the texture of the selected item as per @Wall" must keep the user's
item selected. It tracks which objects it selected itself (per scene, this
process only) and retracts only those when their mention leaves the
composer. The accepted mention's root becomes active only when that doesn't
steal active from a manually selected object. Runs on a short timer
(handler pattern: never mutate selection inside an RNA update callback).
"""

import re

import bpy
from bpy.app.handlers import persistent

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# Same token shape the C++ detector produces/accepts: '@' at start-of-text or
# after whitespace, then a quoted name (spaces allowed) or a bare word.
# Deliberately never matches infix '@' (user@example.com).
_MENTION_RE = re.compile(r'(?:^|(?<=\s))@(?:"([^"]+)"|(\S+))')

# Trailing punctuation users type right after a bare mention ("@Lamp,").
# Only stripped as a SECOND lookup attempt so names like "Lamp.001" resolve
# verbatim first.
_TRAILING_PUNCT = ',.;:!?)'

_SYNC_TIMER_DELAY = 0.05  # after the composer text apply lands

# scene name -> names of objects the LAST sync selected. Lets the next sync
# retract only mention-driven selections while leaving the user's manual
# selection alone. Process-local and cleared on file load.
_MENTION_SELECTED = {}


def retract_names(prev_names, current_names):
    """Mention-selected names to deselect: selected by the previous sync but
    no longer backing any mention in the composer."""
    return set(prev_names) - set(current_names)


def parse_mentions(text):
    """Ordered, de-duplicated mention names in *text*."""
    names = []
    for quoted, bare in _MENTION_RE.findall(text or ""):
        name = quoted or bare
        if name and name not in names:
            names.append(name)
    return names


def _resolve(scene, name):
    """(objects_to_select, root) for a mentioned *name*, ([], None) if unknown."""
    obj = scene.objects.get(name)
    if obj is not None:
        return [obj] + list(getattr(obj, "children_recursive", ())), obj

    mat = bpy.data.materials.get(name)
    if mat is not None:
        users = [
            o for o in scene.objects
            if any(slot.material == mat for slot in o.material_slots)
        ]
        return users, (users[0] if users else None)

    coll = bpy.data.collections.get(name)
    if coll is not None:
        in_scene = {o.name for o in scene.objects}
        objs = [o for o in coll.all_objects if o.name in in_scene]
        return objs, (objs[0] if objs else None)

    return [], None


def _resolve_lenient(scene, name):
    objs, root = _resolve(scene, name)
    if objs:
        return objs, root
    stripped = name.rstrip(_TRAILING_PUNCT)
    if stripped and stripped != name:
        return _resolve(scene, stripped)
    return [], None


def _view_layer_for(scene):
    try:
        if bpy.context.scene == scene and bpy.context.view_layer is not None:
            return bpy.context.view_layer
    except Exception:
        pass
    try:
        return scene.view_layers[0]
    except Exception:
        return None


def sync_selection_to_mentions(scene, active_name=""):
    """Additively select the assets mentioned in the composer; no-op when
    nothing resolves. Never deselects a manual selection — only objects the
    previous sync selected are retracted when their mention is gone. Must be
    called from a main-thread timer/operator, not from inside an RNA update
    callback."""
    if getattr(bpy.context, "mode", 'OBJECT') != 'OBJECT':
        return  # selection flags are an object-mode interaction

    view_layer = _view_layer_for(scene)
    if view_layer is None:
        return

    to_select = []
    active_obj = None
    for name in parse_mentions(scene.mixie_chat_input):
        objs, root = _resolve_lenient(scene, name)
        to_select.extend(objs)
        # Active candidate = the just-accepted mention's root; first
        # resolvable root otherwise.
        if root is not None and (name == active_name or active_obj is None):
            active_obj = root

    if not to_select:
        return

    scene_key = scene.name
    current_names = {obj.name for obj in to_select}
    prev_names = _MENTION_SELECTED.get(scene_key, set())

    # Retract ONLY what a previous sync selected for since-removed mentions.
    for name in retract_names(prev_names, current_names):
        obj = scene.objects.get(name)
        if obj is None:
            continue
        try:
            obj.select_set(False, view_layer=view_layer)
        except Exception:
            pass

    selected_any = False
    for obj in to_select:
        try:
            obj.select_set(True, view_layer=view_layer)
            selected_any = True
        except Exception:
            pass  # not in this view layer / unselectable

    _MENTION_SELECTED[scene_key] = current_names

    if selected_any:
        try:
            # Make the accepted root active only when that doesn't steal
            # active from a manually selected object ("the selected item"
            # must keep meaning the user's pick).
            active = view_layer.objects.active
            active_is_users = (
                active is not None
                and active.select_get(view_layer=view_layer)
                and active.name not in prev_names
                and active.name not in current_names
            )
            if (active_obj is not None and not active_is_users
                    and active_obj.name in view_layer.objects):
                view_layer.objects.active = active_obj
        except Exception:
            pass
        _tag_redraw_view3d()


def _tag_redraw_view3d():
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
    except Exception:
        pass


def schedule_selection_sync(scene, active_name=""):
    """Defer the sync to a timer so it runs after the composer apply, outside
    the RNA update callback that triggered it."""
    scene_name = getattr(scene, "name", None)
    if not scene_name:
        return

    def _run():
        try:
            target = bpy.data.scenes.get(scene_name)
            if target is not None:
                sync_selection_to_mentions(target, active_name)
        except Exception:
            logger.debug("mention selection sync failed", exc_info=True)
        return None

    try:
        bpy.app.timers.register(_run, first_interval=_SYNC_TIMER_DELAY)
    except Exception:
        logger.debug("mention selection sync scheduling failed", exc_info=True)


@persistent
def _on_load_post(_filepath=None):
    # Stale tracking from a previous file could retract an object the user
    # manually selected in the new one — names carry across loads.
    _MENTION_SELECTED.clear()


def register_handlers():
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)


def unregister_handlers():
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    _MENTION_SELECTED.clear()
