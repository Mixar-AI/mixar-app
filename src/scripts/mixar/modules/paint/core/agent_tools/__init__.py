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

from .layer_params import inspect_paint_layer_stack, set_paint_layer_parameters
from .layer_stack import (
    add_procedural_material_layer,
    initialize_empty_layer_paint_project,
    initialize_layer_paint_project,
)
from .layered_manifest import apply_layered_material_manifest
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

__all__ = [
    "add_procedural_material_layer",
    "apply_layered_material_manifest",
    "apply_prepared_scene_materials",
    "enqueue_procedural_material_generation",
    "find_procedural_material",
    "get_prepared_scene_material_status",
    "get_procedural_material_generation_status",
    "initialize_empty_layer_paint_project",
    "initialize_layer_paint_project",
    "inspect_paint_layer_stack",
    "list_procedural_materials",
    "prepare_scene_materials",
    "set_paint_layer_parameters",
]
