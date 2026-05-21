# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Paint bake module.

Organized into subpackages:
- operators/: Bake operator classes
- channel/: Channel baking
- entity/: Entity-to-image baking
- layer/: Layer baking
- merge/: Merge operations
- target/: Target management
- object_prep/: Object preparation
- utils/: Utilities and helpers

This __init__.py uses lazy imports via importlib to avoid circular
dependencies. Imports are resolved on first access rather than at
module load time.
"""

import importlib

# Define what can be exported (for IDE autocomplete and import * support)
__all__ = [
    # Modules
    "bake_info_properties",
    "bake_target_properties",
    # Classes
    "MBakeInfoProps",
    "MBakeTarget",
    # Functions
    "get_objs_size_proportions",
    "update_enable_subdiv_setup",
    "update_subdiv_setup",
    "get_bake_output_quality",
    "get_compositor_node_tree",
    "use_compositor_for_denoise",
    "update_enable_bake_to_vcol",
]

# Cache for imported modules/attributes
_cache = {}


def __getattr__(name):
    """Lazy import to avoid circular dependencies."""
    if name in _cache:
        return _cache[name]

    # Get the parent module path
    parent = __name__  # mixar.modules.paint.ui.bake

    # Module imports
    if name == "bake_info_properties":
        module = importlib.import_module(f"{parent}.utils.bake_info_properties")
        _cache[name] = module
        return module
    if name == "bake_target_properties":
        module = importlib.import_module(f"{parent}.bake_target.bake_target_properties")
        _cache[name] = module
        return module

    # Class imports
    if name == "MBakeInfoProps":
        module = importlib.import_module(f"{parent}.utils.bake_info_properties")
        result = getattr(module, "MBakeInfoProps")
        _cache[name] = result
        return result
    if name == "MBakeTarget":
        module = importlib.import_module(f"{parent}.bake_target.bake_target_properties")
        result = getattr(module, "MBakeTarget")
        _cache[name] = result
        return result

    # Function imports from utils
    if name == "get_objs_size_proportions":
        module = importlib.import_module(f"{parent}.utils.bake_operators_helper")
        result = getattr(module, "get_objs_size_proportions")
        _cache[name] = result
        return result
    if name == "update_enable_subdiv_setup":
        module = importlib.import_module(f"{parent}.utils.bake_operators_helper")
        result = getattr(module, "update_enable_subdiv_setup")
        _cache[name] = result
        return result
    if name == "update_subdiv_setup":
        module = importlib.import_module(f"{parent}.utils.bake_operators_helper")
        result = getattr(module, "update_subdiv_setup")
        _cache[name] = result
        return result
    if name == "get_bake_output_quality":
        module = importlib.import_module(f"{parent}.utils.bake_scene_settings")
        result = getattr(module, "get_bake_output_quality")
        _cache[name] = result
        return result
    if name == "get_compositor_node_tree":
        module = importlib.import_module(f"{parent}.utils.bake_scene_settings")
        result = getattr(module, "get_compositor_node_tree")
        _cache[name] = result
        return result
    if name == "use_compositor_for_denoise":
        module = importlib.import_module(f"{parent}.utils.bake_scene_settings")
        result = getattr(module, "use_compositor_for_denoise")
        _cache[name] = result
        return result
    if name == "update_enable_bake_to_vcol":
        module = importlib.import_module(f"{parent}.utils.bake_utils")
        result = getattr(module, "update_enable_bake_to_vcol")
        _cache[name] = result
        return result

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
