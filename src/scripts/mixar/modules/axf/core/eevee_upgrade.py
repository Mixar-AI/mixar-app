# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Give car paints imported before the EEVEE fit their EEVEE fit (no re-import needed).

Older imports carry no `axf_eevee_fit` image, so EEVEE draws them from the node's rough
`Preview *` inputs. Everything the fit needs is already in the node's table image: the
parameter stream (kd, coat IOR, refraction, lobes, table texel offset) and the colour
table in linear Rec.709. So the fit is rebuilt from that image alone, which also works
when the original .axf was not kept.

Main thread: read the table pixels (a few hundred kilobytes). Worker thread: the numpy
fit (about 1.7 s per paint). Timer: pack each fit and attach it to its node.
"""

from __future__ import annotations

import os
import tempfile
import threading

import numpy as np

from mixar.config.logging_config import get_logger

from .. import constants as C

logger = get_logger(__name__)
_state = {"running": False, "results": None}
_lock = threading.Lock()

H0, H1, H2, H3 = 0, 1, 2, 3


def model_from_table_pixels(rows: np.ndarray) -> dict:
    """The model eevee_fit.fit() reads, from a table image (H, W, 4) whose row 0 is the
    first row the kernel reads (Blender's bottom pixel row)."""
    w = rows.shape[1]
    stream = rows.reshape(-1, 4).astype(np.float64)
    h0, h1, h2, h3 = stream[H0], stream[H1], stream[H2], stream[H3]
    n_lobes = int(min(h1[0], 3))
    nd = int(h2[3])
    row0 = int(h3[0])
    if nd <= 0 or row0 <= 0 or row0 + nd > rows.shape[0]:
        raise ValueError("Not an AxF car paint table image")
    lobes = stream[C.PARAM_HEADER_TEXELS:C.PARAM_HEADER_TEXELS + n_lobes, :3]
    return {
        "kd": float(h0[1]), "ior": float(h0[2]), "refractive": bool(h0[3] != 0.0),
        "lobes": lobes, "table": rows[row0:row0 + nd, :w, :3].astype(np.float64),
        # Already linear Rec.709 and completed: table_rgb709() returns it as is.
        "table_space": "srgb_e", "table_texel_offset": float(h3[3]),
    }


def table_pixels(image) -> np.ndarray:
    """Blender image -> (H, W, 4) float32, row 0 = Blender's bottom row."""
    w, h = image.size
    buf = np.empty(w * h * 4, np.float32)
    image.pixels.foreach_get(buf)
    return buf.reshape(h, w, 4)


def car_paint_nodes_without_fit(materials) -> list:
    """[(material, node)] for every AxF Car Paint node with a table and no EEVEE fit."""
    out = []
    for mat in materials:
        if mat is None or not mat.use_nodes or mat.node_tree is None:
            continue
        for node in mat.node_tree.nodes:
            if (node.bl_idname == C.NODE_IDNAME and node.get(C.PROP_TABLE) is not None
                    and node.get(C.PROP_EEVEE_FIT) is None):
                out.append((mat, node))
    return out


def start(targets, on_done) -> threading.Thread:
    """Fit every target on one worker thread; on_done(results) gets
    [(material name, node name, lut or exception)] on the worker thread."""
    from . import eevee_fit

    jobs = []
    for mat, node in targets:
        try:
            jobs.append((mat.name, node.name, model_from_table_pixels(table_pixels(node[C.PROP_TABLE]))))
        except (ValueError, AttributeError) as e:
            jobs.append((mat.name, node.name, e))

    def run():
        results = []
        for mat_name, node_name, m in jobs:
            if isinstance(m, Exception):
                results.append((mat_name, node_name, m))
                continue
            try:
                results.append((mat_name, node_name, eevee_fit.fit(m)))
            except Exception as e:  # noqa: BLE001 - reported per material
                results.append((mat_name, node_name, e))
        on_done(results)

    thread = threading.Thread(target=run, name="axf_eevee_upgrade", daemon=True)
    thread.start()
    return thread


def is_running() -> bool:
    return _state["running"]


def schedule(targets) -> int:
    """Start fitting targets in the background; a timer attaches the results.
    Returns the number of nodes queued (0 when a run is already in progress)."""
    import bpy

    if _state["running"] or not targets:
        return 0
    _state["running"] = True

    def done(results):
        with _lock:
            _state["results"] = results

    start(targets, done)
    bpy.app.timers.register(_poll, first_interval=0.25)
    return len(targets)


def _poll():
    with _lock:
        results, _state["results"] = _state["results"], None
    if results is None:
        return 0.25
    try:
        _apply(results)
    finally:
        _state["running"] = False
    return None


def _apply(results) -> None:
    import bpy

    from .blender_import import _packed_data_image

    added = 0
    with tempfile.TemporaryDirectory(prefix="mixar_axf_") as tmp:
        for mat_name, node_name, lut in results:
            mat = bpy.data.materials.get(mat_name)
            node = mat.node_tree.nodes.get(node_name) if mat and mat.node_tree else None
            if isinstance(lut, Exception) or node is None:
                logger.warning("[AxF] EEVEE fit for %s skipped: %s", mat_name,
                               lut if isinstance(lut, Exception) else "material changed")
                continue
            if node.get(C.PROP_EEVEE_FIT) is not None:
                continue
            base = mat.name[4:] if mat.name.startswith("AxF ") else mat.name
            node[C.PROP_EEVEE_FIT] = _packed_data_image(f"AxF {base} EEVEE Fit", lut,
                                                        tmp)
            mat.node_tree.update_tag()
            added += 1
    if added:
        bpy.ops.ed.undo_push(message="Add AxF EEVEE Fit")
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type in {'VIEW_3D', 'PROPERTIES'}:
                    area.tag_redraw()
    logger.info("[AxF] EEVEE fit added to %d car paint node(s)", added)
