# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Submit a World Labs splat job — the ONE enqueue path both surfaces share.

The sidebar operator (``mixie.world_labs_generate``) and the canvas node
(``WORLD_LABS`` in ``node_execution.run_action_node``) resolve their source
differently (the tab vs. the connected IMAGE socket) but must stage and
submit identically: catalog ``mode``/``lod``, optional JPEG bytes, and
``enqueue_world_labs_job``. Two copies of that would drift the way a
prompt-only body used to keep the catalog ``image`` default and 422.
"""

from __future__ import annotations

import base64

from mixar.modules.common.job_queue.constants import FEATURE_WORLD_LABS
from mixar.modules.moodboard.core.world_labs_mode import resolve_world_labs_mode


def resolve_world_labs_catalog(
    selected_model: str = "", selected_mode: str = "", selected_lod: str = "",
):
    """Resolve World Labs model parameters exclusively from the live catalog."""
    from mixar.bootstrap.generation_catalog_cache import (
        get_default_model_slug,
        get_model,
    )
    from mixar.modules.common.generation_params import collect_params

    placeholders = {"", "LOADING", "NONE", "ERROR"}
    requested = selected_model or ""
    if requested not in placeholders and get_model("world_labs", requested) is None:
        raise ValueError(f"World Labs model '{requested}' is not enabled")
    model = (
        requested if requested not in placeholders
        else (get_default_model_slug("world_labs") or "")
    )
    model_row = get_model("world_labs", model) if model else None
    if not model_row:
        raise ValueError("No enabled World Labs model is available")

    values = collect_params("world_labs", model)
    schema = model_row.get("parameters") or {}

    def _value(name, explicit):
        spec = schema.get(name) or {}
        value = explicit or values.get(name) or spec.get("default")
        allowed = spec.get("enum")
        if value is None or (allowed is not None and value not in allowed):
            raise ValueError(f"World Labs catalog parameter '{name}' is unavailable")
        return str(value)

    return model, _value("mode", selected_mode), _value("lod", selected_lod)


def run_world_labs_node(context, node):
    """Node-graph runner for ``WORLD_LABS`` (called by ``run_action_node``)."""
    from mixar.modules.common.utils.image_utils import compress_for_service
    from mixar.modules.moodboard.core.media_utils import is_still_item
    from mixar.modules.moodboard.core.node_graph import input_media_items
    from mixar.modules.moodboard.core.node_job_bridge import ensure_graph_listener
    from mixar.modules.moodboard.core.node_schema import (
        collect_node_params,
        node_model_slug,
    )
    from mixar.modules.moodboard.core.world_labs_queue import enqueue_world_labs_job

    stills = [
        item for item in input_media_items(context.scene, node)
        if is_still_item(item)
    ]
    if len(stills) > 1:
        raise ValueError("Generate Splat takes one image")
    image = stills[0].image if stills else None
    prompt = (getattr(node, "prompt", "") or "").strip()
    params = collect_node_params(node)
    model, catalog_mode, lod = resolve_world_labs_catalog(
        selected_model=node_model_slug(node),
        selected_mode=str(params.get("mode") or ""),
        selected_lod=str(params.get("lod") or ""),
    )
    mode = resolve_world_labs_mode(
        catalog_mode, has_image=image is not None, has_prompt=bool(prompt),
    )
    if mode == "image" and image is None:
        raise ValueError("Connect an image or enter a prompt")
    if mode == "text" and not prompt:
        raise ValueError("Enter a prompt in the splat node")

    image_b64 = ""
    label = prompt[:40] if prompt else "World"
    if mode == "image":
        image_bytes = compress_for_service(image, "world_labs")
        image_b64 = base64.b64encode(image_bytes).decode()
        label = image.name

    ensure_graph_listener(FEATURE_WORLD_LABS)
    job = enqueue_world_labs_job(
        mode=mode,
        prompt=prompt,
        model=model,
        lod=lod,
        image_bytes_b64=image_b64,
        label=label,
        graph_node_id=node.node_id,
        scene_name=getattr(context.scene, "name", ""),
    )
    return job, params
