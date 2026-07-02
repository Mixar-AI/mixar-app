# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Scene Asset Filler

Searches the user's asset library for matching assets by label and imports
them to replace wireframe bbox placeholders created during generate_mesh=false
scene reconstruction.
"""

import concurrent.futures
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import bpy

from mixar.modules.common.api.client import HTTPClient
from mixar.config.config import get_server_url
from mixar.config.logging_config import get_logger
from mixar.modules.asset_search.constants import (
    ASSET_SEARCH_BATCH_ENDPOINT,
    ASSET_SEARCH_ENDPOINT,
)
from mixar.modules.moodboard.constants import (
    BATCH_SEARCH_CHUNK_SIZE,
    MIN_SIMILARITY_SCORE,
)

logger = get_logger(__name__)


def _get_client() -> HTTPClient:
    """Return a module-level reusable HTTPClient."""
    global _http_client
    if _http_client is None:
        _http_client = HTTPClient(base_url=get_server_url())
    return _http_client


_http_client: Optional[HTTPClient] = None


def _search_asset(label: str) -> Optional[dict]:
    """
    Search the asset library for a single label.

    Returns the top result dict or None.
    """
    try:
        client = _get_client()
        resp = client.post(
            ASSET_SEARCH_ENDPOINT,
            data={"prompt": label},
            timeout=30,
            raise_for_status=False,
        )

        if resp.status_code == 404:
            logger.debug("[AssetFiller] No trained model (404) for '%s'", label)
            return None

        if not resp.success:
            logger.error("[AssetFiller] Search failed for '%s': %s", label, resp.message or resp.status_code)
            return None

        data = resp.data or {}
        inner = data.get("data") or data
        results = inner.get("results", []) if isinstance(inner, dict) else []

        if not results:
            logger.debug("[AssetFiller] No results for '%s'", label)
            return None

        top = results[0]
        score = top.get("similarity_score", 0)
        if score < MIN_SIMILARITY_SCORE:
            logger.debug("[AssetFiller] Best match for '%s' scored %.2f (below threshold %s)", label, score, MIN_SIMILARITY_SCORE)
            return None

        logger.debug("[AssetFiller] Match for '%s': %s (score=%.2f)", label, top.get('model_name', '?'), score)
        return top

    except Exception as e:
        logger.error("[AssetFiller] Search error for '%s': %s", label, e)
        return None


def _search_assets_batch(labels: Dict[int, str]) -> Dict[int, dict]:
    """
    Batch-search the asset library for multiple labels via the batch endpoint.

    Chunks into groups of BATCH_SEARCH_CHUNK_SIZE to respect the backend limit.
    Falls back to empty dict if batch endpoint is unavailable, letting
    the caller use parallel individual searches instead.

    Args:
        labels: {object_id: label} mapping

    Returns:
        {object_id: top_result_dict} for matches above MIN_SIMILARITY_SCORE.
    """
    if not labels:
        return {}

    import json

    obj_ids = list(labels.keys())
    prompt_list = list(labels.values())
    search_results: Dict[int, dict] = {}

    try:
        client = _get_client()

        for chunk_start in range(0, len(prompt_list), BATCH_SEARCH_CHUNK_SIZE):
            chunk_end = min(chunk_start + BATCH_SEARCH_CHUNK_SIZE, len(prompt_list))
            chunk_prompts = prompt_list[chunk_start:chunk_end]
            chunk_obj_ids = obj_ids[chunk_start:chunk_end]

            resp = client.post(
                ASSET_SEARCH_BATCH_ENDPOINT,
                data={"prompts": json.dumps(chunk_prompts)},
                timeout=30,
                raise_for_status=False,
            )

            if resp.status_code == 404:
                logger.debug("[AssetFiller] Batch endpoint not available (404), using fallback")
                return {}

            if not resp.success:
                logger.warning("[AssetFiller] Batch search failed: %s", resp.message or resp.status_code)
                return {}

            data = resp.data or {}

            if not isinstance(data, dict):
                logger.warning("[AssetFiller] Batch response is not a dict")
                return {}

            envelope_status = data.get("status", "")
            if envelope_status == "failure":
                logger.error("[AssetFiller] Batch search returned failure: %s", data.get('message', 'unknown'))
                return {}

            inner = data.get("data") or data
            all_results = inner.get("results", {}) if isinstance(inner, dict) else {}

            for obj_id, label in zip(chunk_obj_ids, chunk_prompts):
                hits = all_results.get(label, [])
                if not hits:
                    continue
                top = hits[0]
                score = top.get("similarity_score", 0)
                if score < MIN_SIMILARITY_SCORE:
                    logger.debug("[AssetFiller] Best batch match for '%s' scored %.2f (below threshold %s)", label, score, MIN_SIMILARITY_SCORE)
                    continue
                logger.debug("[AssetFiller] Batch match for '%s': %s (score=%.2f)", label, top.get('model_name', '?'), score)
                search_results[obj_id] = top

        return search_results

    except Exception as e:
        logger.error("[AssetFiller] Batch search error: %s", e)
        return {}


def _resolve_blend_path(result: dict) -> Optional[str]:
    """
    Resolve the full .blend file path from a search result.

    Search results contain 'metadata.library' (name) and 'metadata.blend_file'
    (relative path).  We match against Blender's registered asset libraries.
    """
    metadata = result.get("metadata") or {}
    library_name = metadata.get("library", "") or result.get("library", "")
    blend_rel = metadata.get("blend_file", "") or result.get("blend_file", "")

    if not library_name or not blend_rel:
        logger.warning("[AssetFiller] Missing identity fields: library='%s', blend_file='%s'", library_name, blend_rel)
        return None

    try:
        for lib in bpy.context.preferences.filepaths.asset_libraries:
            if lib.name == library_name:
                full_path = Path(lib.path) / blend_rel
                if full_path.exists():
                    return str(full_path)
                logger.warning("[AssetFiller] Blend file not found: %s", full_path)
                return None
    except Exception as e:
        logger.error("[AssetFiller] Library resolution error: %s", e)

    logger.warning("[AssetFiller] Library '%s' not found in preferences", library_name)
    return None


def _import_asset_on_main_thread(
    blend_path: str,
    asset_name: str,
    placeholder_obj,
    object_id: int,
    on_filled: Optional[Callable],
) -> bool:
    """Import an asset from a .blend file and replace the placeholder (main thread).

    Returns:
        True if the placeholder was actually replaced, False otherwise.
    """
    from mixar.modules.moodboard.core import scene_importer

    try:
        imported_objs = []

        # Try importing as object first, then as collection
        with bpy.data.libraries.load(blend_path, link=False) as (data_from, data_to):
            if asset_name in data_from.objects:
                data_to.objects = [asset_name]
            elif asset_name in data_from.collections:
                data_to.collections = [asset_name]

        # Collect imported objects
        if hasattr(data_to, 'objects') and data_to.objects:
            imported_objs = [o for o in data_to.objects if o is not None]
        elif hasattr(data_to, 'collections') and data_to.collections:
            coll = data_to.collections[0] if data_to.collections else None
            if coll:
                imported_objs = list(coll.objects)

        if not imported_objs:
            logger.warning("[AssetFiller] No objects imported for '%s'", asset_name)
            return False

        # Replace the placeholder
        result = scene_importer.replace_placeholder(placeholder_obj, imported_objs)

        if result and on_filled:
            try:
                on_filled(object_id, asset_name)
            except Exception as e:
                logger.error("[AssetFiller] on_filled callback error: %s", e)
        return bool(result)

    except Exception as e:
        logger.error("[AssetFiller] Import failed for '%s': %s", asset_name, e)
        return False


def fill_placeholders_from_library(
    placeholder_map: Dict[int, Tuple],
    on_filled: Optional[Callable] = None,
    on_complete: Optional[Callable] = None,
):
    """
    Search the asset library for each placeholder label and import matches.

    Args:
        placeholder_map: {object_id: (blender_obj, label)} wireframe placeholders
        on_filled: Callback(object_id, asset_name) per successful replacement
        on_complete: Callback(filled_count, total_count) when all done
    """
    if not placeholder_map:
        if on_complete:
            on_complete(0, 0)
        return

    total = len(placeholder_map)
    logger.debug("[AssetFiller] Starting asset search for %s placeholders", total)

    def background_search():
        """Search API: try batch first, fall back to parallel individual."""
        timings: Dict[str, float] = {}

        # Try batch search first
        labels = {obj_id: label for obj_id, (_, label) in placeholder_map.items()}
        timings["batch_start"] = time.monotonic()
        search_results = _search_assets_batch(labels)
        timings["batch_end"] = time.monotonic()

        if not search_results:
            # Fallback: parallel individual searches
            timings["individual_start"] = time.monotonic()

            def search_one(item):
                obj_id, (_, label) = item
                return obj_id, _search_asset(label)

            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                futures = {
                    executor.submit(search_one, item): item
                    for item in placeholder_map.items()
                }
                for future in concurrent.futures.as_completed(futures):
                    try:
                        obj_id, result = future.result()
                        if result:
                            search_results[obj_id] = result
                    except Exception as e:
                        logger.error("[AssetFiller] Search thread error: %s", e)

            timings["individual_end"] = time.monotonic()

        timings["search_end"] = time.monotonic()

        # Post results back to main thread
        def apply_results():
            _apply_search_results(
                placeholder_map, search_results, on_filled, on_complete,
                timings,
            )
            return None

        bpy.app.timers.register(apply_results, first_interval=0.0)

    thread = threading.Thread(target=background_search, daemon=True)
    thread.start()


def _apply_search_results(
    placeholder_map: Dict[int, Tuple],
    search_results: Dict[int, dict],
    on_filled: Optional[Callable],
    on_complete: Optional[Callable],
    timings: Optional[Dict[str, float]] = None,
):
    """Apply search results on the main thread: import assets, replace placeholders."""
    if timings is None:
        timings = {}
    placement_start = time.monotonic()
    total = len(placeholder_map)
    filled = 0

    if not search_results:
        logger.debug("[AssetFiller] No matches found for any placeholder")
        if on_complete:
            on_complete(0, total)
        return

    for obj_id, result in search_results.items():
        entry = placeholder_map.get(obj_id)
        if not entry:
            continue

        placeholder_obj, label = entry
        asset_name = result.get("model_name", "")
        blend_path = _resolve_blend_path(result)

        if not blend_path or not asset_name:
            logger.warning("[AssetFiller] Cannot resolve asset for '%s'", label)
            continue

        # Check placeholder still exists
        try:
            _ = placeholder_obj.name
        except ReferenceError:
            logger.warning("[AssetFiller] Placeholder for '%s' was already removed", label)
            continue

        if _import_asset_on_main_thread(
            blend_path, asset_name, placeholder_obj, obj_id, on_filled,
        ):
            filled += 1

    placement_end = time.monotonic()
    timings["placement_start"] = placement_start
    timings["placement_end"] = placement_end

    # Print timing summary
    def _dur(start_key: str, end_key: str):
        s, e = timings.get(start_key), timings.get(end_key)
        return (e - s) if s is not None and e is not None else None

    logger.debug("[AssetFiller] Filled %s/%s placeholders", filled, total)
    logger.debug("[AssetFiller] ===== Timing Summary =====")
    batch_dur = _dur("batch_start", "batch_end")
    individual_dur = _dur("individual_start", "individual_end")
    placement_dur = _dur("placement_start", "placement_end")
    total_dur = _dur("batch_start", "placement_end")

    if batch_dur is not None:
        logger.debug("[AssetFiller]   Batch Search: %.2fs", batch_dur)
    if individual_dur is not None:
        logger.debug("[AssetFiller]   Individual Search (fallback): %.2fs", individual_dur)
    if placement_dur is not None:
        logger.debug("[AssetFiller]   Asset Placement: %.2fs", placement_dur)
    if total_dur is not None:
        logger.debug("[AssetFiller]   -- Total (asset fill): %.2fs", total_dur)
    logger.debug("[AssetFiller] ================================")

    if on_complete:
        try:
            on_complete(filled, total)
        except Exception as e:
            logger.error("[AssetFiller] on_complete callback error: %s", e)
