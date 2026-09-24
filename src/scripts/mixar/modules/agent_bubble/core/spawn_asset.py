# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Place a library asset into the visible 3D viewport.

Add to Scene used to call ``bpy.ops.wm.append``. That operator returns
``{'CANCELLED'}`` without raising when the path does not explode, and from
the bubble it instantiates into the view layer's active collection — often
excluded — with no View3D to frame the result. ``bpy.ops`` treats the
return as success, so the button reported "Added" and the grid stayed empty.

This loads the datablock with ``bpy.data.libraries.load`` and links it into
a collection the user can see, then frames it in the main window's 3D view.
"""

from __future__ import annotations

import logging

import bpy

logger = logging.getLogger(__name__)

_SLOTS = {"object": "objects", "collection": "collections"}
_MEASURABLE = {"MESH", "CURVE", "SURFACE", "META", "FONT"}


def spawn_library_asset(context, blend_path, id_dir, asset_name):
    """Append *asset_name* from *blend_path* into the viewport scene.

    Returns ``(ok, message)``. Success means at least one object was linked
    into a collection that is not excluded from the viewport's view layer.
    """
    blend = (blend_path or "").strip()
    name = (asset_name or "").strip()
    kind = (id_dir or "Object").strip() or "Object"
    if not blend or not name:
        return False, "That asset has no file on disk"
    if not _is_file(blend):
        return False, "The asset's .blend is missing"
    slot = _SLOTS.get(kind.lower())
    if slot is None:
        return False, "Only objects and collections can be added to the scene"

    try:
        with bpy.data.libraries.load(blend, link=False) as (data_from, data_to):
            available = list(getattr(data_from, slot, []) or [])
            if name not in available:
                return False, f"'{name}' is not in that file anymore"
            setattr(data_to, slot, [name])
    except Exception:
        logger.exception("[Generations] Could not read '%s' from %s", name, blend)
        return False, f"Could not add '{name}' to the scene"

    loaded = [
        item
        for item in list(getattr(data_to, slot, []) or [])
        if item is not None and not isinstance(item, str)
    ]
    if not loaded:
        return False, "The asset appended empty."

    target = _viewport_target(context)
    if target is None or target.scene is None:
        return False, "No scene is open to add this to"
    scene = target.scene
    view_layer = target.view_layer

    if slot == "collections":
        members = _link_collection_asset(scene, loaded[0])
    else:
        collection = _visible_collection(scene, view_layer)
        members = []
        for obj in loaded:
            if _link_object(collection, obj):
                members.append(obj)
    if not members:
        return False, "The asset appended empty."

    _touch_view_layer(view_layer)
    members = _realize_instancers(context, target, view_layer, members)
    _move_to_cursor(scene, members)
    _touch_view_layer(view_layer)
    _ensure_object_mode(context, target, view_layer)
    _reveal(view_layer, members)
    _frame(context, target)
    _redraw(target)
    return True, f"Added '{name}' to the scene"


def _is_file(path):
    import os

    try:
        return os.path.isfile(path)
    except OSError:
        return False


def _link_object(collection, obj):
    objects = getattr(collection, "objects", None)
    if objects is None:
        return False
    try:
        if obj.name in objects:
            return True
    except TypeError:
        pass
    try:
        objects.link(obj)
    except RuntimeError:
        return False
    return True


def _link_collection_asset(scene, coll):
    try:
        coll.hide_viewport = False
    except Exception:  # noqa: BLE001 — a collection without the flag still links
        pass
    children = scene.collection.children
    try:
        already = coll.name in children
    except TypeError:
        already = False
    if not already:
        children.link(coll)
    return list(getattr(coll, "all_objects", None) or getattr(coll, "objects", []) or [])


def _visible_collection(scene, view_layer):
    active = None
    layer = getattr(view_layer, "active_layer_collection", None)
    if layer is not None:
        active = getattr(layer, "collection", None)
    if _collection_visible(view_layer, active):
        return active
    return scene.collection


def _collection_visible(view_layer, collection):
    if collection is None or getattr(collection, "hide_viewport", False):
        return False
    layer_coll = _find_layer_collection(
        getattr(view_layer, "layer_collection", None), collection
    )
    if layer_coll is None:
        return True
    return not getattr(layer_coll, "exclude", False) and not getattr(
        layer_coll, "hide_viewport", False
    )


def _find_layer_collection(layer_coll, collection):
    if layer_coll is None:
        return None
    if getattr(layer_coll, "collection", None) == collection:
        return layer_coll
    for child in getattr(layer_coll, "children", []) or []:
        found = _find_layer_collection(child, collection)
        if found is not None:
            return found
    return None


def _viewport_target(context):
    """The main window's VIEW_3D, falling back to the caller's scene.

    The bubble is a temp window with no 3D view. Prefer any other window
    that has one, so the asset lands in the viewport the user is looking at.
    """
    current = getattr(context, "window", None)
    windows = list(getattr(getattr(context, "window_manager", None), "windows", []) or [])
    ordered = [win for win in windows if win is not current]
    if current is not None:
        ordered.append(current)
    for window in ordered:
        found = _view3d_in(window)
        if found is not None:
            area, region, space = found
            return _Target(
                window=window,
                area=area,
                region=region,
                space=space,
                scene=getattr(window, "scene", None) or getattr(context, "scene", None),
                view_layer=getattr(window, "view_layer", None)
                or getattr(context, "view_layer", None),
            )
    scene = getattr(context, "scene", None)
    if scene is None:
        return None
    return _Target(
        window=None,
        area=None,
        region=None,
        space=None,
        scene=scene,
        view_layer=getattr(context, "view_layer", None),
    )


class _Target:
    def __init__(self, window, area, region, space, scene, view_layer):
        self.window = window
        self.area = area
        self.region = region
        self.space = space
        self.scene = scene
        self.view_layer = view_layer


def _view3d_in(window):
    screen = getattr(window, "screen", None)
    for area in getattr(screen, "areas", []) or []:
        if getattr(area, "type", None) != "VIEW_3D":
            continue
        region = next(
            (reg for reg in (getattr(area, "regions", []) or []) if getattr(reg, "type", None) == "WINDOW"),
            None,
        )
        if region is None:
            continue
        space = next(
            (sp for sp in (getattr(area, "spaces", []) or []) if getattr(sp, "type", None) == "VIEW_3D"),
            None,
        )
        return area, region, space
    return None


def _realize_instancers(context, target, view_layer, members):
    instancers = [
        obj
        for obj in members
        if getattr(obj, "type", "") == "EMPTY"
        and getattr(obj, "instance_type", "") == "COLLECTION"
        and getattr(obj, "instance_collection", None) is not None
    ]
    if not instancers or target is None or target.area is None:
        return members
    try:
        _deselect(view_layer)
        for obj in instancers:
            obj.select_set(True)
        view_layer.objects.active = instancers[0]
        before = set(bpy.data.objects)
        _run_in_viewport(context, target, lambda: bpy.ops.object.duplicates_make_real(
            use_base_parent=True, use_hierarchy=True
        ))
        members = list(members)
        members.extend(obj for obj in bpy.data.objects if obj not in before)
    except Exception:
        logger.debug("[Generations] Could not realize collection instances", exc_info=True)
    return members


def _move_to_cursor(scene, members):
    points = []
    for obj in members:
        points.extend(_world_points(obj, 0))
    cursor = _xyz(getattr(getattr(scene, "cursor", None), "location", (0.0, 0.0, 0.0)))
    roots = _roots(members)
    if not points:
        return
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    zs = [point[2] for point in points]
    offset = (
        cursor[0] - (min(xs) + max(xs)) / 2.0,
        cursor[1] - (min(ys) + max(ys)) / 2.0,
        cursor[2] - min(zs),
    )
    for obj in roots:
        loc = _xyz(getattr(obj, "location", (0.0, 0.0, 0.0)))
        obj.location = (loc[0] + offset[0], loc[1] + offset[1], loc[2] + offset[2])


def _roots(members):
    group = set(members)
    roots = [obj for obj in members if getattr(obj, "parent", None) not in group]
    return roots or list(members)


def _world_points(obj, depth):
    points = []
    if getattr(obj, "type", "") in _MEASURABLE:
        matrix = getattr(obj, "matrix_world", None)
        for corner in getattr(obj, "bound_box", []) or []:
            points.append(_xyz(_apply(matrix, corner)))
    if (
        depth < 4
        and getattr(obj, "type", "") == "EMPTY"
        and getattr(obj, "instance_type", "") == "COLLECTION"
        and getattr(obj, "instance_collection", None) is not None
    ):
        for child in getattr(obj.instance_collection, "all_objects", []) or []:
            points.extend(_world_points(child, depth + 1))
    return points


def _apply(matrix, corner):
    if matrix is None:
        return corner
    try:
        return matrix @ corner
    except TypeError:
        return corner


def _xyz(value):
    if hasattr(value, "x"):
        return (float(value.x), float(value.y), float(value.z))
    return (float(value[0]), float(value[1]), float(value[2]))


def _ensure_object_mode(context, target, view_layer):
    active = getattr(getattr(view_layer, "objects", None), "active", None)
    if active is None or getattr(active, "mode", "OBJECT") == "OBJECT":
        return
    if target is None or target.area is None:
        return
    try:
        _run_in_viewport(context, target, lambda: bpy.ops.object.mode_set(mode="OBJECT"))
    except Exception:
        logger.debug("[Generations] Could not leave edit mode", exc_info=True)


def _reveal(view_layer, members):
    _deselect(view_layer)
    for obj in members:
        try:
            obj.hide_viewport = False
        except Exception:  # noqa: BLE001
            pass
        try:
            obj.hide_set(False)
        except Exception:  # noqa: BLE001
            pass
        try:
            obj.select_set(True)
        except Exception:  # noqa: BLE001
            pass
    roots = _roots(members)
    if roots and getattr(view_layer, "objects", None) is not None:
        try:
            view_layer.objects.active = roots[0]
        except Exception:  # noqa: BLE001
            pass


def _deselect(view_layer):
    objects = getattr(view_layer, "objects", None)
    if objects is None:
        return
    try:
        current = list(objects)
    except TypeError:
        return
    for obj in current:
        try:
            obj.select_set(False)
        except Exception:  # noqa: BLE001
            pass


def _frame(context, target):
    if target is None or target.area is None:
        return
    try:
        _run_in_viewport(context, target, lambda: bpy.ops.view3d.view_selected())
    except Exception:
        logger.debug("[Generations] Could not frame the asset", exc_info=True)


def _run_in_viewport(context, target, fn):
    temp = getattr(context, "temp_override", None)
    if temp is None or target.window is None:
        fn()
        return
    override = {
        "window": target.window,
        "area": target.area,
        "region": target.region,
        "scene": target.scene,
        "view_layer": target.view_layer,
    }
    if target.space is not None:
        override["space_data"] = target.space
    with temp(**override):
        fn()


def _redraw(target):
    if target is None or target.area is None:
        return
    redraw = getattr(target.area, "tag_redraw", None)
    if redraw is not None:
        redraw()


def _touch_view_layer(view_layer):
    update = getattr(view_layer, "update", None)
    if update is not None:
        update()
