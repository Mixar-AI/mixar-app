# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Vegetation Asset Loader

Appends Botaniq vegetation/rock .blend assets by id to use as scatter instance
sources. Assets are NOT bundled (Botaniq's licence forbids redistribution) — they're
loaded at runtime from the user's licensed install via ``MIXAR_BOTANIQ_PATH`` (the
folder containing the Botaniq ``models/`` tree), with a dev fallback. Sources are
parked in a hidden ``BotaniqSources`` collection and used only as GN instances.
"""

import os

import bpy

_SOURCES_COLLECTION = "BotaniqSources"

# asset id -> (path relative to the Botaniq models dir, object name inside the .blend)
BOTANIQ_ASSETS = {
    "pebble":         ("rocks/bq_Rock_Pebble_A_spring-summer-autumn.blend", "bq_Rock_Pebble_A_spring-summer-autumn"),
    "rock":           ("rocks/bq_Rock_Basalt-Photoscan_A_spring-summer-autumn.blend", "bq_Rock_Basalt-Photoscan_A_spring-summer-autumn"),
    "grass":          ("grass/bq_Grass_Lolium-perenne_A_spring-summer.blend", "bq_Grass_Lolium-perenne_A_spring-summer"),
    "grass_dry":      ("grass/bq_Grass-Dry_Lolium-perenne_A_spring-summer.blend", "bq_Grass-Dry_Lolium-perenne_A_spring-summer"),
    "daisy":          ("flowers/bq_Flower_Bellis-perennis_A_spring-summer.blend", "bq_Flower_Bellis-perennis_A_spring-summer"),
    "dandelion":      ("weed/bq_Weed_Taraxacum-officinale_A_spring-summer.blend", "bq_Weed_Taraxacum-officinale_A_spring-summer"),
    "fern":           ("plants/bq_Plant_Dryopteris-carthusiana_A_spring-summer-autumn.blend", "bq_Plant_Dryopteris-carthusiana_A_spring-summer-autumn"),
    "shrub":          ("shrubs/bq_Shrub_Sambucus-nigra_A_summer.blend", "bq_Shrub_Sambucus-nigra_A_summer"),
    "tree_deciduous": ("deciduous/bq_Tree_Aesculus-hippocastanum_A_summer.blend", "bq_Tree_Aesculus-hippocastanum_A_summer"),
    "tree_crabapple": ("deciduous/bq_Tree_Malus-domestica_A_summer.blend", "bq_Tree_Malus-domestica_A_summer"),
    "tree_conifer":   ("coniferous/bq_Tree_Pinus-pinaster_A_spring-summer-autumn.blend", "bq_Tree_Pinus-pinaster_A_spring-summer-autumn"),
    "sapling":        ("sapling/bq_Sapling_Acer-pseudoplatanus_A_summer.blend", "bq_Sapling_Acer-pseudoplatanus_A_summer"),
}

_cache = {}


def botaniq_models_dir():
    """The Botaniq ``models/`` directory, from env or a dev fallback. None if absent."""
    candidates = [
        os.environ.get("MIXAR_BOTANIQ_PATH", ""),
        os.path.expanduser("~/Documents/botaniq/models"),
        "/tmp/botaniq/botaniq_starter/blends/models",
    ]
    for p in candidates:
        if p and os.path.isdir(p):
            return p
    return None


def _sources_collection():
    coll = bpy.data.collections.get(_SOURCES_COLLECTION)
    if coll is None:
        coll = bpy.data.collections.new(_SOURCES_COLLECTION)
        bpy.context.scene.collection.children.link(coll)
        # hidden from view + render; only referenced as GN instance sources.
        lc = bpy.context.view_layer.layer_collection.children.get(_SOURCES_COLLECTION)
        if lc:
            lc.exclude = True
    return coll


def load_asset(asset_id, base_path=None):
    """Append the Botaniq asset object for ``asset_id`` (cached). Returns it or None."""
    cached = _cache.get(asset_id)
    if cached is not None and cached.name in bpy.data.objects:
        return cached
    base = base_path or botaniq_models_dir()
    spec = BOTANIQ_ASSETS.get(asset_id)
    if not base or not spec:
        return None
    path = os.path.join(base, spec[0])
    if not os.path.isfile(path):
        return None
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        want = [n for n in src.objects if n == spec[1]] or list(src.objects)
        dst.objects = want
    obj = next((o for o in dst.objects if o is not None and o.type == "MESH"), None)
    if obj is None:
        return None
    obj.hide_render = True
    coll = _sources_collection()
    if obj.name not in coll.objects:
        coll.objects.link(obj)
    _cache[asset_id] = obj
    return obj
