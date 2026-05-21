# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Paint UI layer module.

Organized into subpackages:
- properties/: Layer property definitions
- operators/: Layer operator classes
- callbacks/: Property update callbacks
- helpers/: Creation and operation helpers
- channel/: Channel-specific functionality
- utils/: Utility functions

This __init__.py uses lazy imports via importlib to avoid circular
dependencies. Imports are resolved on first access rather than at
module load time.
"""

import importlib

# Define what can be exported (for IDE autocomplete and import * support)
__all__ = [
    # Module
    "layer_properties",
    # Classes
    "MLayer",
    "MLayerChannel",
    "register",
    "unregister",
    # Constants
    "DEFAULT_NEW_IMG_SUFFIX",
    "DEFAULT_NEW_VCOL_SUFFIX",
    "DEFAULT_NEW_VDM_SUFFIX",
    # Helper functions
    "add_new_layer",
    "channel_items",
    "get_normal_map_type_items",
    "remove_layer",
    "replace_layer_type",
    "update_layer_channel_override",
    "update_layer_channel_override_1",
    "update_layer_channel_override_vcol_name",
    "duplicate_layer_nodes_and_images",
    # Callback functions
    "check_override_1_layer_channel_nodes",
    "check_override_layer_channel_nodes",
    # Operators
    "MClearBrushTexture",
    "MOpenImageToBrushTexture",
    "MOpenImageToOverride1Channel",
    "MOpenImageToOverrideChannel",
    "MSelectExistingImage",
]

# Cache for imported modules/attributes
_cache = {}


def __getattr__(name):
    """Lazy import to avoid circular dependencies."""
    if name in _cache:
        return _cache[name]

    # Get the parent module path
    parent = __name__  # mixar.modules.paint.ui.layer

    # Module imports
    if name == "layer_properties":
        module = importlib.import_module(f"{parent}.properties.layer_properties")
        _cache[name] = module
        return module

    # Class imports from properties
    if name == "MLayer":
        module = importlib.import_module(f"{parent}.properties.layer_properties")
        result = getattr(module, "MLayer")
        _cache[name] = result
        return result
    if name == "MLayerChannel":
        module = importlib.import_module(f"{parent}.properties.layer_channel_properties")
        result = getattr(module, "MLayerChannel")
        _cache[name] = result
        return result
    if name == "register":
        module = importlib.import_module(f"{parent}.properties.layer_properties")
        result = getattr(module, "register")
        _cache[name] = result
        return result
    if name == "unregister":
        module = importlib.import_module(f"{parent}.properties.layer_properties")
        result = getattr(module, "unregister")
        _cache[name] = result
        return result

    # Constants from helpers
    if name == "DEFAULT_NEW_IMG_SUFFIX":
        module = importlib.import_module(f"{parent}.helpers.layer_enum_helpers")
        result = getattr(module, "DEFAULT_NEW_IMG_SUFFIX")
        _cache[name] = result
        return result
    if name == "DEFAULT_NEW_VCOL_SUFFIX":
        module = importlib.import_module(f"{parent}.helpers.layer_enum_helpers")
        result = getattr(module, "DEFAULT_NEW_VCOL_SUFFIX")
        _cache[name] = result
        return result
    if name == "DEFAULT_NEW_VDM_SUFFIX":
        module = importlib.import_module(f"{parent}.helpers.layer_enum_helpers")
        result = getattr(module, "DEFAULT_NEW_VDM_SUFFIX")
        _cache[name] = result
        return result

    # Helper functions
    if name == "add_new_layer":
        module = importlib.import_module(f"{parent}.helpers.layer_create_helpers")
        result = getattr(module, "add_new_layer")
        _cache[name] = result
        return result
    if name == "channel_items":
        module = importlib.import_module(f"{parent}.helpers.layer_enum_helpers")
        result = getattr(module, "channel_items")
        _cache[name] = result
        return result
    if name == "get_normal_map_type_items":
        module = importlib.import_module(f"{parent}.helpers.layer_enum_helpers")
        result = getattr(module, "get_normal_map_type_items")
        _cache[name] = result
        return result
    if name == "remove_layer":
        module = importlib.import_module(f"{parent}.helpers.layer_operation_helpers")
        result = getattr(module, "remove_layer")
        _cache[name] = result
        return result
    if name == "replace_layer_type":
        module = importlib.import_module(f"{parent}.helpers.layer_operation_helpers")
        result = getattr(module, "replace_layer_type")
        _cache[name] = result
        return result
    if name == "update_layer_channel_override":
        module = importlib.import_module(f"{parent}.callbacks.layer_override_callbacks")
        result = getattr(module, "update_layer_channel_override")
        _cache[name] = result
        return result
    if name == "update_layer_channel_override_1":
        module = importlib.import_module(f"{parent}.callbacks.layer_override_callbacks")
        result = getattr(module, "update_layer_channel_override_1")
        _cache[name] = result
        return result
    if name == "update_layer_channel_override_vcol_name":
        module = importlib.import_module(f"{parent}.callbacks.layer_state_callbacks")
        result = getattr(module, "update_layer_channel_override_vcol_name")
        _cache[name] = result
        return result
    if name == "duplicate_layer_nodes_and_images":
        module = importlib.import_module(f"{parent}.helpers.layer_duplicate_helpers")
        result = getattr(module, "duplicate_layer_nodes_and_images")
        _cache[name] = result
        return result

    # Callback functions
    if name == "check_override_1_layer_channel_nodes":
        module = importlib.import_module(f"{parent}.callbacks.layer_override_callbacks")
        result = getattr(module, "check_override_1_layer_channel_nodes")
        _cache[name] = result
        return result
    if name == "check_override_layer_channel_nodes":
        module = importlib.import_module(f"{parent}.callbacks.layer_override_callbacks")
        result = getattr(module, "check_override_layer_channel_nodes")
        _cache[name] = result
        return result

    # Operators
    if name == "MClearBrushTexture":
        module = importlib.import_module(f"{parent}.channel.channel_image_operators")
        result = getattr(module, "MClearBrushTexture")
        _cache[name] = result
        return result
    if name == "MOpenImageToBrushTexture":
        module = importlib.import_module(f"{parent}.channel.channel_image_operators")
        result = getattr(module, "MOpenImageToBrushTexture")
        _cache[name] = result
        return result
    if name == "MOpenImageToOverride1Channel":
        module = importlib.import_module(f"{parent}.channel.channel_image_operators")
        result = getattr(module, "MOpenImageToOverride1Channel")
        _cache[name] = result
        return result
    if name == "MOpenImageToOverrideChannel":
        module = importlib.import_module(f"{parent}.channel.channel_image_operators")
        result = getattr(module, "MOpenImageToOverrideChannel")
        _cache[name] = result
        return result
    if name == "MSelectExistingImage":
        module = importlib.import_module(f"{parent}.channel.channel_image_operators")
        result = getattr(module, "MSelectExistingImage")
        _cache[name] = result
        return result

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
