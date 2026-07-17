# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""'@' mention candidate registry for the Mixie Chat composer.

Supplies the names the mention dropdown can complete: every object of the
current scene (components included — the dropdown scrolls, so a chair's
legs/slats/cushion are all reachable), materials, and asset-marked
datablocks. Modeled on the dev
scene-graph registry/store (scripts/dev/scene_graph/{registry,store}.py):
one module-level singleton, name-keyed candidates, a cheap dirty flag set
from a depsgraph handler and lazy refresh on query — so per-keystroke
searches never walk bpy.data unless something actually changed.

Flow (see mixie_chat_mention.cc for the C++ half):
  keystroke -> C++ publishes scene.mixie_chat_mention_query
            -> on_mention_query_changed (ui/properties/mention_props.py)
            -> REGISTRY.search() here -> fills scene.mixie_chat_mention_items
"""

from collections import namedtuple

import bpy
from bpy.app.handlers import persistent

from mixar.config.logging_config import get_logger
from ..constants import MENTION_INSERT_MAXLEN, MENTION_MAX_ITEMS

logger = get_logger(__name__)

# Candidate kinds — must match mention_kind_icon()/mention_kind_label() in
# mixie_chat_mention.cc.
KIND_OBJECT = 0
KIND_MATERIAL = 1
KIND_ASSET = 2

# bpy.data containers scanned for asset-marked datablocks.
_ASSET_CONTAINERS = (
    "objects",
    "materials",
    "collections",
    "images",
    "node_groups",
    "worlds",
    "actions",
    "brushes",
)

Candidate = namedtuple("Candidate", ("name", "kind"))
Match = namedtuple("Match", ("name", "kind", "insert_text"))


def format_mention(name):
    """Replacement text inserted into the composer for *name*.

    Names with whitespace are quoted so the mention stays one readable unit
    in the prompt; the trailing space ends the token, which is what closes
    the dropdown after accepting.
    """
    if any(ch.isspace() for ch in name):
        text = '@"{}" '.format(name)
    else:
        text = "@{} ".format(name)
    return text if len(text.encode("utf-8")) <= MENTION_INSERT_MAXLEN else ""


def rank_matches(candidates, query, limit=MENTION_MAX_ITEMS):
    """Rank *candidates* (iterable of Candidate) against *query*.

    Case-insensitive. Prefix matches beat word-boundary prefixes beat
    substrings; ties break on shorter, then alphabetical, names. An empty
    query (bare '@') lists everything, objects first.
    Returns at most *limit* Match tuples.
    """
    query = (query or "").lower()
    scored = []
    for cand in candidates:
        name_lower = cand.name.lower()
        if not query:
            score = 0
        elif name_lower.startswith(query):
            score = 0
        elif any(
            word.startswith(query)
            for word in name_lower.replace("_", " ").replace("-", " ").replace(".", " ").split()
        ):
            score = 1
        elif query in name_lower:
            score = 2
        else:
            continue
        scored.append((score, cand.kind, len(cand.name), name_lower, cand))

    scored.sort(key=lambda entry: entry[:4])

    matches = []
    for entry in scored:
        cand = entry[4]
        insert_text = format_mention(cand.name)
        if not insert_text:
            continue  # pathologically long name — cannot be inserted
        matches.append(Match(cand.name, cand.kind, insert_text))
        if len(matches) >= limit:
            break
    return matches


class MentionRegistry:
    """Lazily refreshed candidate list (singleton, see REGISTRY below)."""

    def __init__(self):
        self._candidates = []
        self._scene_name = None
        self._dirty = True

    # -- handler-facing (must stay cheap) ----------------------------------

    def note_dirty(self):
        self._dirty = True

    # -- query-facing (lazy heavy work) -------------------------------------

    def search(self, query, scene, limit=MENTION_MAX_ITEMS):
        self._ensure_fresh(scene)
        return rank_matches(self._candidates, query, limit)

    # -- internals -----------------------------------------------------------

    def _ensure_fresh(self, scene):
        scene_name = getattr(scene, "name", None)
        if not self._dirty and scene_name == self._scene_name:
            return
        self._candidates = self._gather(scene)
        self._scene_name = scene_name
        self._dirty = False

    @staticmethod
    def _gather(scene):
        candidates = []
        seen = set()

        def add(name, kind):
            key = (name, kind)
            if name and not name.startswith(".") and key not in seen:
                seen.add(key)
                candidates.append(Candidate(name, kind))

        try:
            # ALL objects, not just roots — component parts (a chair's legs,
            # slats, cushion) must be mentionable; the dropdown scrolls.
            for obj in scene.objects:
                add(obj.name, KIND_OBJECT)
        except Exception:
            logger.debug("mention registry: object scan failed", exc_info=True)

        try:
            for mat in bpy.data.materials:
                add(mat.name, KIND_MATERIAL)
        except Exception:
            logger.debug("mention registry: material scan failed", exc_info=True)

        for container in _ASSET_CONTAINERS:
            try:
                for datablock in getattr(bpy.data, container, ()):
                    if getattr(datablock, "asset_data", None) is not None:
                        add(datablock.name, KIND_ASSET)
            except Exception:
                logger.debug(
                    "mention registry: asset scan of bpy.data.%s failed", container, exc_info=True
                )

        return candidates


# Module-level singleton (mirrors the dev scene-graph STORE pattern).
REGISTRY = MentionRegistry()


@persistent
def _on_depsgraph_update(scene, depsgraph=None):
    """Any datablock edit (add/delete/rename/reparent) marks the registry
    dirty; the actual rescan happens lazily on the next '@' query."""
    REGISTRY.note_dirty()


@persistent
def _on_load_post(_filepath=None):
    REGISTRY.note_dirty()


def register_handlers():
    if _on_depsgraph_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph_update)
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)


def unregister_handlers():
    if _on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph_update)
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
