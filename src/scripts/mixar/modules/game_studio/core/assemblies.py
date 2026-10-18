# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Assemblies: the object a game role belongs to.

Agent-built scenes are multi-part assets under empties::

    WorkspaceRoot_…            container (scene-wide; never an assembly)
      SF_Gameplay              container (its children are themselves assets)
        gameplay_elements_Token00     <- assembly root: a token
          …_Disk  …_Rim  …_Bolt       parts
      SF_HeroBike              <- assembly root: the bike
        hero_bicycle_ChainStay-1 …    ~60 parts (maybe in sub-groups)

``assembly_root(part)`` climbs from a part while the parent is NOT a
container and returns the highest object reached. A container is an
object named like a scene-wide grouping (``WorkspaceRoot_*``, ``Scene``,
``Collection``, ``Root``, ``World``, ``Level``, ``Environment``) or one whose
children are mostly groups themselves (at least two, and at least half of
its children): it holds several assets, not the parts of one.

``Hierarchy`` builds the parent → children map once from a scene's objects
(``Object.children`` scans every object on each call in Blender).
"""

from __future__ import annotations

import re

CONTAINER_WORDS = ("workspaceroot", "scene", "collection", "root", "world", "level", "environment")
MIN_GROUP_CHILDREN = 2
GROUP_SHARE = 0.5


def _first_word(name: str) -> str:
    words = [w for w in re.split(r"[^A-Za-z0-9]+", str(name or "").lower()) if w]
    return words[0] if words else ""


class Hierarchy:
    """Parent/children view over ``objects`` (objects need ``name`` and
    ``parent``)."""

    def __init__(self, objects):
        self.objects = list(objects)
        self._children: dict[int, list] = {}
        for obj in self.objects:
            parent = getattr(obj, "parent", None)
            if parent is not None:
                self._children.setdefault(id(parent), []).append(obj)
        self._container: dict[int, bool] = {}
        self._root: dict[int, object] = {}

    def children(self, obj) -> list:
        return self._children.get(id(obj), [])

    def descendants(self, obj) -> list:
        found, stack = [], list(self.children(obj))
        while stack:
            child = stack.pop()
            found.append(child)
            stack.extend(self.children(child))
        return found

    def is_container(self, obj) -> bool:
        key = id(obj)
        if key not in self._container:
            name = str(getattr(obj, "name", "")).lower()
            kids = self.children(obj)
            groups = sum(1 for kid in kids if self.children(kid))
            self._container[key] = (
                name.startswith("workspaceroot") or _first_word(name) in CONTAINER_WORDS
                or (groups >= MIN_GROUP_CHILDREN and groups >= GROUP_SHARE * len(kids)))
        return self._container[key]

    def assembly_root(self, obj):
        """The asset ``obj`` is a part of (``obj`` itself for a loose object
        or a container)."""
        key = id(obj)
        if key not in self._root:
            root = obj
            if not self.is_container(obj):
                parent = getattr(obj, "parent", None)
                while parent is not None and not self.is_container(parent):
                    root, parent = parent, getattr(parent, "parent", None)
            self._root[key] = root
        return self._root[key]

    def assemblies(self, objects=None) -> list:
        """Distinct roots of ``objects`` (default: all), in first-seen order."""
        roots, seen = [], set()
        for obj in self.objects if objects is None else objects:
            root = self.assembly_root(obj)
            if id(root) not in seen:
                seen.add(id(root))
                roots.append(root)
        return roots

    def parts(self, root) -> list:
        """The assembly's meshes: ``root`` itself when it is one, plus every
        descendant mesh."""
        own = [root] if getattr(root, "type", "") == "MESH" else []
        return own + [o for o in self.descendants(root) if getattr(o, "type", "") == "MESH"]
