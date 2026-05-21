# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer properties subpackage.

This __init__.py is intentionally minimal to avoid circular imports.
Uses lazy imports via importlib to prevent recursion issues.
"""

import importlib
import sys

# Cache for imported modules/attributes
_cache = {}


def __getattr__(name):
    """Lazy import to avoid circular dependencies."""
    if name in _cache:
        return _cache[name]

    # Get the parent module path
    parent = __name__  # mixar.modules.paint.ui.layer.properties

    if name == "layer_properties":
        module = importlib.import_module(f"{parent}.layer_properties")
        _cache[name] = module
        return module
    elif name == "MLayer":
        module = importlib.import_module(f"{parent}.layer_properties")
        result = getattr(module, "MLayer")
        _cache[name] = result
        return result
    elif name == "MLayerChannel":
        module = importlib.import_module(f"{parent}.layer_channel_properties")
        result = getattr(module, "MLayerChannel")
        _cache[name] = result
        return result
    elif name == "register":
        module = importlib.import_module(f"{parent}.layer_properties")
        result = getattr(module, "register")
        _cache[name] = result
        return result
    elif name == "unregister":
        module = importlib.import_module(f"{parent}.layer_properties")
        result = getattr(module, "unregister")
        _cache[name] = result
        return result

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
