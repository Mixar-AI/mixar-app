# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pure suggestion-ladder builder. No bpy — unit-testable outside Blender.

Given an indexed snapshot of the scene and the user's current selection,
produce an ordered list of suggestion *levels* — alternative selections the
user can cycle through, narrow to broad:

    1. same parts in this asset      (the other 3 legs of this stool)
    2. same parts scene-wide         (all 8 stool legs)
    3. the whole asset               (the entire stool)
    4. all instances of the asset    (both stools)
    5. everything with this material (all Charcoal Powder Coat objects)

Levels are ALTERNATIVES, not nested scopes: applying one replaces the
selection with (seed selection ∪ level set). They are ordered by object
count so cycling feels like growth, but e.g. "whole asset" is not a
superset of "same parts scene-wide" — the chip labels make each hop
explicit.
"""

from collections import namedtuple

from ..constants import GEOMETRY_TYPES
from .keys import pretty_label

# A snapshot of one scene object, gathered by registry.py (or built by
# tests directly).
ObjectRecord = namedtuple(
    "ObjectRecord",
    (
        "name",       # object name
        "obj_type",   # 'MESH', 'CURVE', 'EMPTY', ...
        "root",       # topmost parent's name (own name when unparented)
        "signature",  # keys.geometry_signature() result
        "stem",       # keys.name_stem() result
        "materials",  # tuple of material names, slot order
    ),
)

Level = namedtuple("Level", ("key", "label", "names"))  # names: frozenset


class SceneSnapshotIndex:
    """Lookup maps over a list of ObjectRecords."""

    def __init__(self, records):
        self.records = {r.name: r for r in records}
        self.by_root = {}
        self.by_signature = {}
        self.by_stem = {}
        self.by_material = {}
        self.root_stems = {}  # root name -> stem of the root record
        for r in records:
            self.by_root.setdefault(r.root, set()).add(r.name)
            self.by_signature.setdefault(r.signature, set()).add(r.name)
            self.by_stem.setdefault(r.stem, set()).add(r.name)
            for mat in r.materials:
                self.by_material.setdefault(mat, set()).add(r.name)
        for r in records:
            if r.name == r.root:
                self.root_stems[r.root] = r.stem


def _same_part_names(index, rec, within=None):
    """Objects matching *rec* by geometry signature OR name stem, of the
    same object type. Optionally restricted to the *within* name set.

    Geometry objects only: empties/cameras/lights share degenerate
    signatures (an asset-root empty would "match" every other root)."""
    if rec.obj_type not in GEOMETRY_TYPES:
        return set()
    candidates = set(index.by_signature.get(rec.signature, ()))
    candidates |= index.by_stem.get(rec.stem, set())
    candidates = {
        n for n in candidates if index.records[n].obj_type == rec.obj_type
    }
    if within is not None:
        candidates &= within
    return candidates


def build_ladder(index, active_name, selected_names, max_level_objects=400):
    """Return a list of Level tuples for the given selection state.

    *index* is a SceneSnapshotIndex; *active_name* the active object's name;
    *selected_names* an iterable of currently selected names (the seed).
    Empty/duplicate/oversized levels are dropped; every level strictly adds
    at least one object over the seed.
    """
    rec = index.records.get(active_name)
    if rec is None:
        return []

    seed = frozenset(selected_names) | {active_name}
    levels = []
    seen_sets = set()

    def add(key, label, names):
        names = frozenset(names) | seed
        if names in seen_sets or names == seed:
            return
        if len(names) > max_level_objects:
            return
        seen_sets.add(names)
        levels.append(Level(key, label, names))

    asset_names = index.by_root.get(rec.root, {active_name})
    asset_label = pretty_label(rec.root)

    # 1. Same parts within this asset.
    local_parts = _same_part_names(index, rec, within=asset_names)
    if len(local_parts) > 1:
        add(
            "same_part_asset",
            "{} matching parts in {}".format(len(local_parts | seed), asset_label),
            local_parts,
        )

    # 2. Same parts scene-wide.
    scene_parts = _same_part_names(index, rec)
    if len(scene_parts | seed) > len(local_parts | seed):
        add(
            "same_part_scene",
            "{} matching parts in scene".format(len(scene_parts | seed)),
            scene_parts,
        )

    # 3. The whole asset.
    if len(asset_names) > 1:
        add(
            "asset",
            "Whole {} ({} objects)".format(asset_label, len(asset_names | seed)),
            asset_names,
        )

    # 4. All instances of this asset (roots sharing the root's stem).
    root_stem = index.root_stems.get(rec.root)
    if root_stem:
        instance_roots = [
            root for root, stem in index.root_stems.items() if stem == root_stem
        ]
        if len(instance_roots) > 1:
            union = set()
            for root in instance_roots:
                union |= index.by_root.get(root, set())
            add(
                "instances",
                "All {} {} assets ({} objects)".format(
                    len(instance_roots), asset_label, len(union | seed)
                ),
                union,
            )

    # 5. Everything sharing the active object's primary material.
    if rec.materials:
        mat = rec.materials[0]
        mat_names = index.by_material.get(mat, set())
        if len(mat_names) > 1:
            add(
                "material",
                '{} objects with "{}"'.format(len(mat_names | seed), mat),
                mat_names,
            )

    # Narrow-to-broad ordering; stable for equal sizes (build order above).
    levels.sort(key=lambda lv: len(lv.names))
    return levels
