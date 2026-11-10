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
# ID properties that tie a file to its creator's published things. A remix
# must not inherit them: publishing it would overwrite the original.
IDENTITY_PROPS = ("mixar_game_store",)
# Registered Scene properties that belong to the creator's session: the
# agent conversation, its ids and the creator's user id.
PRIVATE_PREFIXES = ("mixie_",)
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


def scrub(scene) -> list[str]:
    """Remove the creator's identity and conversation from ``scene``.

    Run on the copy that is uploaded as a remix source, and again on a
    downloaded source before it is used (a .mixar attached on the web never
    went through the first pass). Returns the names it cleared.
    """
    cleared = []
    for name in IDENTITY_PROPS:
        if scene.get(name) is not None:
            del scene[name]
            cleared.append(name)
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
    return cleared
