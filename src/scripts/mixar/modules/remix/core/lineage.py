# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""What a project was remixed from, and what must not travel with a copy.

Pure functions over anything scene-shaped (ID properties through
``get``/``[]``/``del``), so the standalone suite runs them on fakes.
"""

from __future__ import annotations

import json

from ..constants import REMIX_PROP, TITLE_SUFFIX

ORIGIN_KEYS = ("kind", "id", "slug", "title", "author", "url")
# Registered Scene properties that belong to the creator's session: the
# agent conversation, its ids and the creator's user id. Also the prefix of
# the agent's resume cursor (``mixie_ws_resume``), an ordinary custom property.
PRIVATE_PREFIXES = ("mixie_",)
# Other keys that tie a file to its creator, stored either way:
#   mixar_game_store / mixar_web_publish  what they published (a remix must
#       never inherit it: publishing would overwrite the original)
#   mixar_scene_id, mixar_workspace_*     the agent's scene and lane identity
#   mixar_rig_job_id                      a job on the creator's account
#   mixar_op_history_id                   their local operation log
PRIVATE_KEYS = ("mixar_game_store", "mixar_web_publish", "mixar_scene_id", "mixar_workspace_token",
                "mixar_workspace_state", "mixar_workspace_merge_plan", "mixar_rig_job_id",
                "mixar_op_history_id")
WEB_PUBLISH_ATTR = "mixar_web_publish"


def clean_origin(origin) -> dict | None:
    """The store's ``origin`` reduced to known keys, or None when unusable."""
    if not isinstance(origin, dict) or origin.get("kind") not in ("post", "game") or not origin.get("id"):
        return None
    author = origin.get("author") if isinstance(origin.get("author"), dict) else {}
    return {
        "kind": str(origin["kind"]), "id": str(origin["id"]),
        "slug": str(origin["slug"]) if origin.get("slug") else None,
        "title": str(origin.get("title") or "")[:140],
        "author": {"handle": author.get("handle") or None,
                   "display_name": str(author.get("display_name") or "Unknown")[:80]},
        "url": str(origin.get("url") or ""),
    }


def stamp(scene, origin) -> dict | None:
    """Record ``origin`` on ``scene``. Returns what was stored."""
    clean = clean_origin(origin)
    if clean is None:
        return None
    scene[REMIX_PROP] = json.dumps(clean, sort_keys=True)
    return clean


def origin_of(scene) -> dict | None:
    raw = scene.get(REMIX_PROP) if scene is not None else None
    if not raw:
        return None
    try:
        return clean_origin(json.loads(raw))
    except (TypeError, ValueError):
        return None


def clear(scene) -> None:
    if scene.get(REMIX_PROP) is not None:
        del scene[REMIX_PROP]


def game_fields(origin) -> dict:
    """Store fields a game publish adds for its lineage. Only a game can be
    the parent of a game (the store keeps posts and games apart)."""
    origin = clean_origin(origin)
    if origin is None or origin["kind"] != "game":
        return {}
    return {"remixed_from_id": origin["id"]}


def post_fields(origin) -> dict:
    origin = clean_origin(origin)
    if origin is None or origin["kind"] != "post":
        return {}
    return {"remixed_from_id": origin["id"]}


def credit_line(origin) -> str:
    origin = clean_origin(origin)
    if origin is None:
        return ""
    author = origin["author"]
    who = f"@{author['handle']}" if author["handle"] else author["display_name"]
    return f"Remixed from {origin['title']} by {who}"


def remix_slug(slug: str, token: str, limit: int = 48) -> str:
    """A slug for a remix that cannot equal its parent's or another remix's:
    the parent slug plus a short random ``token``. Without it a remix of your
    own remix would land on the first one's store page and overwrite it."""
    token = "".join(ch for ch in str(token).lower() if ch.isalnum())[:6] or "x"
    base = str(slug or "remix").strip("-")[:limit - len(token) - 1].strip("-") or "remix"
    return f"{base}-{token}"


def remix_title(title: str, limit: int = 80) -> str:
    title = str(title or "").strip() or "Untitled"
    if title.endswith(TITLE_SUFFIX):
        return title[:limit]
    return title[:limit - len(TITLE_SUFFIX)].rstrip() + TITLE_SUFFIX


def _private_names(scene) -> list[str]:
    rna = getattr(scene, "bl_rna", None)
    props = getattr(rna, "properties", None) or ()
    return [p.identifier for p in props
            if any(p.identifier.startswith(prefix) for prefix in PRIVATE_PREFIXES)]


def _is_private(key: str) -> bool:
    return key.startswith(PRIVATE_PREFIXES) or key in PRIVATE_KEYS


def has_system_props(idblock) -> bool:
    return callable(getattr(idblock, "bl_system_properties_get", None))


def system_props(idblock):
    """Where Blender keeps the values of registered properties (5.0+), or None.

    The values stay in the file whether or not the property is registered in
    the process that opens it. A background Mixar registers none of the chat
    properties, so the conversation is only reachable (and removable) here.
    """
    getter = getattr(idblock, "bl_system_properties_get", None)
    if getter is None:
        return None
    try:
        return getter()
    except (AttributeError, RuntimeError, TypeError):
        return None


def _custom_keys(idblock) -> list[str]:
    """Names of the ordinary custom properties on ``idblock``."""
    try:
        return [str(key) for key in idblock.keys()]
    except (AttributeError, RuntimeError, TypeError):
        return []


def private_keys(idblock) -> list[str]:
    """Private data still stored on ``idblock`` (empty once it is clean):
    stored values of registered properties, and ordinary custom properties."""
    stored = system_props(idblock)
    found = {key for key in (stored.keys() if stored is not None else ()) if _is_private(key)}
    found.update(key for key in _custom_keys(idblock) if _is_private(key))
    return sorted(found)


def scrub_stored(idblock) -> list[str]:
    """Delete private values from ``idblock``, in both places they can be
    kept; returns their names."""
    cleared = []
    stored = system_props(idblock)
    if stored is not None:
        for key in [k for k in stored.keys() if _is_private(k)]:
            try:
                del stored[key]
            except (KeyError, RuntimeError, TypeError):
                continue
            cleared.append(key)
    for key in [k for k in _custom_keys(idblock) if _is_private(k)]:
        try:
            del idblock[key]
        except (KeyError, RuntimeError, TypeError):
            continue
        cleared.append(key)
    return cleared


def all_ids(data) -> list:
    """Every datablock in ``data`` (``bpy.data``): scenes, objects, window
    managers, texts and whatever a later version adds. Found by walking the
    collections rather than naming them, so a new data type is covered."""
    seen, found = set(), []
    for name in dir(data):
        if name.startswith("_"):
            continue
        try:
            collection = getattr(data, name)
            items = list(collection) if hasattr(collection, "__iter__") and hasattr(collection, "keys") else []
        except (AttributeError, RuntimeError, TypeError):
            continue
        for item in items:
            marker = id(item) if not hasattr(item, "as_pointer") else item.as_pointer()
            if hasattr(item, "name") and marker not in seen:
                seen.add(marker)
                found.append(item)
    return found


def scrub_file(data) -> int:
    """Clean every datablock of an open file. Returns how many values went."""
    cleared = 0
    for scene in getattr(data, "scenes", ()):
        cleared += len(scrub(scene))
    for idblock in all_ids(data):
        cleared += len(scrub_stored(idblock))
    return cleared


def leftovers(data) -> dict:
    """``{datablock name: [keys]}`` for anything private still in the file."""
    found = {}
    for idblock in all_ids(data):
        keys = private_keys(idblock)
        if keys:
            found[f"{type(idblock).__name__}:{getattr(idblock, 'name', '?')}"] = keys
    return found


def scrub(scene) -> list[str]:
    """Remove the creator's identity and conversation from ``scene``.

    Run on the copy that is uploaded as a remix source, and again on a
    downloaded source before it is used (a .mixar attached on the web never
    went through the first pass). Returns the names it cleared.

    The same data is reachable three ways, and all three are cleared: through
    the registered properties (the app), as stored values (a background
    process, where those properties are not registered), and as ordinary
    custom properties.
    """
    cleared = []
    for name in _private_names(scene):
        value = getattr(scene, name, None)
        try:
            if hasattr(value, "clear") and not isinstance(value, (str, bytes)):
                value.clear()  # a CollectionProperty (the chat transcript)
            else:
                scene.property_unset(name)
        except (AttributeError, RuntimeError, TypeError):
            continue
        cleared.append(name)
    publish = getattr(scene, WEB_PUBLISH_ATTR, None)
    if publish is not None:
        for prop in getattr(getattr(publish, "bl_rna", None), "properties", None) or ():
            if prop.identifier != "rna_type":
                try:
                    publish.property_unset(prop.identifier)
                except (AttributeError, RuntimeError, TypeError):
                    pass
        cleared.append(WEB_PUBLISH_ATTR)
    cleared.extend(name for name in scrub_stored(scene) if name not in cleared)
    return cleared
