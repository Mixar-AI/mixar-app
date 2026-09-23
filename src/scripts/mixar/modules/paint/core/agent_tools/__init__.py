# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent-facing helpers for Mixar Paint layer-stack workflows.

Typed backend tools call into this package (``paint.core.agent_tools``) to
initialize Mixar Paint projects, inspect/edit layer stacks, search procedural
libraries, queue MatGen jobs, and apply prepared scene materials. The public
surface below is split across focused submodules to stay maintainable; import
paths into ``paint.core.agent_tools`` are unchanged.
"""

from __future__ import annotations

from .layer_authoring import (
    add_fill_layer,
    add_layer_mask,
    add_library_layer,
    focus_material_slot,
    set_layer_channel,
)
from .layer_params import inspect_paint_layer_stack, set_paint_layer_parameters
from .layer_stack import (
    add_procedural_material_layer,
    initialize_empty_layer_paint_project,
    initialize_layer_paint_project,
)
from .layered_manifest import apply_layered_material_manifest
from .layered_slots import prepare_real_scale_uvs
from .material_inventory import inspect_material_slots
from .material_library import (
    enqueue_procedural_material_generation,
    find_procedural_material,
    get_procedural_material_generation_status,
    list_procedural_materials,
)
from .scene_materials import (
    apply_prepared_scene_materials,
    get_prepared_scene_material_status,
    prepare_scene_materials,
)
from .real_scale_uv import REAL_SCALE_UV_NAME

# Capabilities backend apply scripts probe with a plain import (an older
# client raises ImportError): ``slot_targets`` — the manifest apply builds a
# fresh datablock into exact slots itself; ``real_scale`` — manifests with
# ``scale.tile_size_m`` render at that physical repeat size;
# ``layer_authoring`` — material-targeted fill / mask / channel / library
# layer helpers and the slot inventory.
AGENT_TOOLS_FEATURES = {"slot_targets": 1, "real_scale": 1, "layer_authoring": 1}

__all__ = [
    "AGENT_TOOLS_FEATURES",
    "REAL_SCALE_UV_NAME",
    "add_fill_layer",
    "add_layer_mask",
    "add_library_layer",
    "add_procedural_material_layer",
    "apply_layered_material_manifest",
    "apply_prepared_scene_materials",
    "enqueue_procedural_material_generation",
    "find_procedural_material",
    "focus_material_slot",
    "get_prepared_scene_material_status",
    "get_procedural_material_generation_status",
    "initialize_empty_layer_paint_project",
    "initialize_layer_paint_project",
    "inspect_material_slots",
    "inspect_paint_layer_stack",
    "list_procedural_materials",
    "prepare_real_scale_uvs",
    "prepare_scene_materials",
    "set_layer_channel",
    "set_paint_layer_parameters",
]
