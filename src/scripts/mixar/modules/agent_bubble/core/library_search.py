# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The island Library tab's search row: one semantic search at a time.

The C++ pane (``agent_ui_generations.cc``) draws a query field and a
reference-image chip. Confirming the query, picking an image or switching
to/from the Materials chip calls :func:`request`, which runs the backend
search (``asset_search/core/search_api.py``) on a worker thread and hands the
result back through ``bpy.app.timers``. The pane reads the outcome from four
WindowManager properties (``generations_props``):

* ``mixar_generations_search_state`` — IDLE / RUNNING / DONE / ERROR;
* ``mixar_generations_search_hits`` — one line per hit, best first:
  ``score<TAB>library<TAB>blend_file<TAB>id_dir<TAB>name`` (forward slashes),
  matched against the gathered asset tiles by ``agent_ui_generations_search.cc``;
* ``mixar_generations_search_message`` — a short status line;
* ``mixar_generations_query`` / ``mixar_generations_search_ref`` — the inputs.

Every search is a metered backend call, so the same (query, image, kind) is
never sent twice in a row, and a stale reply (the user searched again before
it landed) is dropped.
"""

import functools
import os
import threading

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.asset_search.constants import (
    ASSET_KIND_MATERIAL,
    SEARCH_TYPE_ALL,
    SEARCH_TYPE_MATERIAL,
)
from mixar.modules.common.i18n import n_, rpt_

logger = get_logger(__name__)

#: Hits per search: enough to fill the grid's visible rows twice over.
TOP_K = 20
#: Largest reference image read for a search (the backend caps uploads too).
MAX_REF_BYTES = 10 * 1024 * 1024

_state = {"seq": 0, "key": None}


def _asset_type(wm):
    return SEARCH_TYPE_MATERIAL if wm.mixar_generations_filter == 'MATERIAL' else SEARCH_TYPE_ALL


def _id_dir(row):
    """The ID folder a hit lives under in its .blend, as the pane's tiles name it."""
    if row.get("kind") == ASSET_KIND_MATERIAL:
        return "Material"
    if str(row.get("type", "")).lower() == "collection":
        return "Collection"
    return "Object"


def format_hits(rows):
    """Result rows -> the pane's hit lines (pure; unit-tested)."""
    lines = []
    for row in rows:
        fields = (
            f"{float(row.get('score', 0.0)):.4f}",
            str(row.get("library", "")),
            str(row.get("blend_file", "")).replace("\\", "/"),
            _id_dir(row),
            str(row.get("name", "")),
        )
        if not fields[4] or any("\t" in f or "\n" in f for f in fields):
            continue
        lines.append("\t".join(fields))
    return "\n".join(lines)


def _redraw():
    from mixar.modules.agent_bubble.ui.properties.generations_props import redraw_bubbles

    redraw_bubbles()


def clear(wm=None, inputs=True):
    """Back to the plain grid. ``inputs`` also empties the query and image."""
    wm = wm or bpy.context.window_manager
    _state["seq"] += 1  # any reply still in flight is now stale
    _state["key"] = None
    if inputs:
        # Setting these fires their update (request), which lands back here
        # with nothing to search; harmless.
        if wm.mixar_generations_query:
            wm.mixar_generations_query = ""
        if wm.mixar_generations_search_ref:
            wm.mixar_generations_search_ref = ""
    wm.mixar_generations_search_hits = ""
    wm.mixar_generations_search_message = ""
    wm.mixar_generations_search_state = 'IDLE'
    _redraw()


def request(context=None):
    """Search for the current inputs, unless that exact search is already shown."""
    wm = (context or bpy.context).window_manager
    query = (wm.mixar_generations_query or "").strip()
    ref = wm.mixar_generations_search_ref or ""
    if not query and not ref:
        clear(wm, inputs=False)
        return
    key = (query, ref, _asset_type(wm))
    if key == _state["key"] and wm.mixar_generations_search_state in {'RUNNING', 'DONE'}:
        return
    _state["key"] = key
    _state["seq"] += 1
    seq = _state["seq"]
    wm.mixar_generations_search_state = 'RUNNING'
    wm.mixar_generations_search_message = ""
    wm.mixar_generations_scroll = 0.0
    threading.Thread(
        target=_worker, args=(seq, *key), name="mixar-library-search", daemon=True,
    ).start()
    _redraw()


def on_filter_changed(context):
    """A shown search follows the Materials chip (it changes the backend filter)."""
    wm = context.window_manager
    if wm.mixar_generations_search_state in {'RUNNING', 'DONE'}:
        request(context)


def _read_reference(path):
    """(bytes, filename) of the reference image, or raises OSError/ValueError."""
    if os.path.getsize(path) > MAX_REF_BYTES:
        raise ValueError("reference image is larger than 10 MB")
    with open(path, "rb") as fh:
        return fh.read(), os.path.basename(path)


def _worker(seq, query, ref, asset_type):
    """Worker thread: read the image, call the backend. Never touches bpy data."""
    from mixar.modules.asset_search.core.search_api import search

    try:
        image_bytes, filename = _read_reference(ref) if ref else (None, "search_query.jpg")
    except (OSError, ValueError) as exc:
        result = {"success": False, "results": [],
                  "message": rpt_("Could not read the reference image: {error}").format(error=exc)}
    else:
        result = search(query, image_bytes, filename, top_k=TOP_K, asset_type=asset_type)
    bpy.app.timers.register(functools.partial(_apply, seq, result), first_interval=0.0)


def _apply(seq, result):
    """Main thread: publish a reply unless a newer search superseded it."""
    if seq != _state["seq"]:
        return None
    try:
        wm = bpy.context.window_manager
        if result.get("success"):
            rows = result.get("results") or []
            wm.mixar_generations_search_hits = format_hits(rows)
            wm.mixar_generations_search_message = "" if rows else n_("No matches")
            wm.mixar_generations_search_state = 'DONE'
        else:
            wm.mixar_generations_search_hits = ""
            wm.mixar_generations_search_message = result.get("message") or n_("Search failed")
            wm.mixar_generations_search_state = 'ERROR'
            _state["key"] = None  # let the same search be retried
        _redraw()
    except Exception:  # noqa: BLE001 — a lost reply must never break the timer loop
        logger.exception("[LibrarySearch] could not publish search results")
    return None
