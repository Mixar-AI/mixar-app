"""
Collection handlers for Blender MCP Bridge.
Provides collection-level operations: list, create.
"""

import bpy
from ..utils.response import ok_response, error_response, not_found
from . import register_handler


def _handle_collection_list(params):
    """
    List all collections in the current Blender file.

    Route: POST /api/collection/list

    Returns:
        Array of {name, objects, children, color_tag, hide_viewport, hide_render}.
    """
    try:
        collections = []

        for col in bpy.data.collections:
            collections.append({
                "name": col.name,
                "objects": [obj.name for obj in col.objects],
                "children": [child.name for child in col.children],
                "color_tag": col.color_tag,
                "hide_viewport": col.hide_viewport,
                "hide_render": col.hide_render,
            })

        return ok_response(collections)
    except Exception as e:
        return error_response(f"Failed to list collections: {e}")


def _handle_collection_create(params):
    """
    Create a new collection and link it into a parent collection.

    Route: POST /api/collection/create

    Params:
        name (str): Name for the new collection.
        parent (str, optional): Parent collection name. Defaults to the scene master collection.
        color_tag (str, optional): Color tag (COLOR_01 … COLOR_08, or NONE).

    Returns:
        {name, parent, color_tag}
    """
    name = params.get("name")
    if not name:
        return error_response("Parameter 'name' is required.")

    parent_name = params.get("parent")
    color_tag = params.get("color_tag")

    try:
        # Resolve parent collection.
        if parent_name:
            parent_col = bpy.data.collections.get(parent_name)
            if parent_col is None:
                return not_found(parent_name, "Collection")
        else:
            # Default: link to the scene's master collection.
            parent_col = bpy.context.scene.collection

        # Create the new collection datablock.
        new_col = bpy.data.collections.new(name)

        # Apply color tag if provided.
        if color_tag:
            VALID_COLOR_TAGS = {
                'NONE',
                'COLOR_01', 'COLOR_02', 'COLOR_03', 'COLOR_04',
                'COLOR_05', 'COLOR_06', 'COLOR_07', 'COLOR_08',
            }
            normalized = color_tag.upper()
            if normalized not in VALID_COLOR_TAGS:
                # Clean up the already-created datablock before returning the error.
                bpy.data.collections.remove(new_col)
                return error_response(
                    f"Invalid color_tag '{color_tag}'. "
                    f"Valid values are: {', '.join(sorted(VALID_COLOR_TAGS))}."
                )
            new_col.color_tag = normalized

        # Link into parent.
        parent_col.children.link(new_col)

        return ok_response({
            "name": new_col.name,
            "parent": parent_col.name,
            "color_tag": new_col.color_tag,
        })
    except Exception as e:
        return error_response(f"Failed to create collection: {e}")


def _handle_collection_add_object(params):
    """
    Link an existing object to a collection, optionally unlinking from current collections.

    Route: POST /api/collection/add-object

    Params:
        collection_name (str): Name of the target collection.
        object_name (str): Name of the object to add.
        unlink_current (bool, optional): Unlink from current collection(s) first. Defaults to False.

    Returns:
        {collection_name, object_name, success}
    """
    collection_name = params.get("collection_name")
    object_name = params.get("object_name")

    if not collection_name:
        return error_response("Parameter 'collection_name' is required.")
    if not object_name:
        return error_response("Parameter 'object_name' is required.")

    try:
        collection = bpy.data.collections.get(collection_name)
        if collection is None:
            return not_found(collection_name, "Collection")

        obj = bpy.data.objects.get(object_name)
        if obj is None:
            return not_found(object_name)

        # Optionally unlink from all current collections.
        if params.get("unlink_current", False):
            for col in list(bpy.data.collections):
                if obj.name in col.objects:
                    col.objects.unlink(obj)
            # Also check the scene master collection.
            scene_col = bpy.context.scene.collection
            if obj.name in scene_col.objects:
                scene_col.objects.unlink(obj)

        # Link the object into the target collection.
        try:
            collection.objects.link(obj)
        except RuntimeError:
            # Object is already in this collection — treat as success.
            pass

        return ok_response({
            "collection_name": collection.name,
            "object_name": obj.name,
            "success": True,
        })
    except Exception as e:
        return error_response(f"Failed to add object to collection: {e}")


def _handle_collection_delete(params):
    """
    Delete a collection. Objects are NOT deleted — they remain in the scene.

    Route: POST /api/collection/delete

    Params:
        name (str): Name of the collection to delete.

    Returns:
        {name, objects_orphaned}
    """
    name = params.get("name")
    if not name:
        return error_response("Parameter 'name' is required.")

    try:
        col = bpy.data.collections.get(name)
        if col is None:
            return not_found(name, "Collection")

        objects_orphaned = [obj.name for obj in col.objects]
        bpy.data.collections.remove(col)

        return ok_response({
            "name": name,
            "objects_orphaned": objects_orphaned,
        })
    except Exception as e:
        return error_response(f"Failed to delete collection: {e}")


def _handle_collection_remove_object(params):
    """
    Remove (unlink) an object from a collection.

    Route: POST /api/collection/remove-object

    Params:
        collection_name (str): Name of the collection.
        object_name (str): Name of the object to remove.

    Returns:
        {collection_name, object_name}
    """
    collection_name = params.get("collection_name")
    object_name = params.get("object_name")

    if not collection_name:
        return error_response("Parameter 'collection_name' is required.")
    if not object_name:
        return error_response("Parameter 'object_name' is required.")

    try:
        col = bpy.data.collections.get(collection_name)
        if col is None:
            return not_found(collection_name, "Collection")

        obj = bpy.data.objects.get(object_name)
        if obj is None:
            return not_found(object_name)

        if obj.name not in col.objects:
            return error_response(
                f"Object '{object_name}' is not in collection '{collection_name}'."
            )

        col.objects.unlink(obj)

        return ok_response({
            "collection_name": col.name,
            "object_name": obj.name,
        })
    except Exception as e:
        return error_response(f"Failed to remove object from collection: {e}")


def _handle_collection_set_visibility(params):
    """
    Toggle visibility properties of a collection.

    Route: POST /api/collection/set-visibility

    Params:
        name (str): Name of the collection.
        hide_viewport (bool, optional): Hide/show in viewport.
        hide_render (bool, optional): Hide/show in renders.

    Returns:
        {name, hide_viewport, hide_render}
    """
    name = params.get("name")
    if not name:
        return error_response("Parameter 'name' is required.")

    try:
        col = bpy.data.collections.get(name)
        if col is None:
            return not_found(name, "Collection")

        if "hide_viewport" in params:
            col.hide_viewport = bool(params["hide_viewport"])
        if "hide_render" in params:
            col.hide_render = bool(params["hide_render"])

        return ok_response({
            "name": col.name,
            "hide_viewport": col.hide_viewport,
            "hide_render": col.hide_render,
        })
    except Exception as e:
        return error_response(f"Failed to set collection visibility: {e}")


# ─── Register routes ───
register_handler("collection", "list", _handle_collection_list)
register_handler("collection", "create", _handle_collection_create)
register_handler("collection", "add-object", _handle_collection_add_object)
register_handler("collection", "delete", _handle_collection_delete)
register_handler("collection", "remove-object", _handle_collection_remove_object)
register_handler("collection", "set-visibility", _handle_collection_set_visibility)
