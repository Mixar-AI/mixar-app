# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer type handler registry.

Provides factory functions for getting the appropriate handler for a layer type.
"""

from typing import Dict, Optional
from .base_handler import LayerTypeHandler, DefaultLayerHandler


# Registry of layer type handlers
_HANDLERS: Dict[str, LayerTypeHandler] = {}

# Default handler for unregistered types
_DEFAULT_HANDLER = DefaultLayerHandler()


def register_handler(layer_type: str, handler: LayerTypeHandler) -> None:
    """Register a handler for a layer type.

    Args:
        layer_type: Layer type string (e.g., 'COLOR', 'IMAGE').
        handler: Handler instance for this layer type.
    """
    _HANDLERS[layer_type] = handler


def get_handler(layer_type: str) -> LayerTypeHandler:
    """Get the handler for a layer type.

    Args:
        layer_type: Layer type string.

    Returns:
        Handler instance, or default handler if type not registered.
    """
    return _HANDLERS.get(layer_type, _DEFAULT_HANDLER)


def get_handler_for_layer(layer) -> LayerTypeHandler:
    """Get the handler for a layer object.

    Args:
        layer: YLayer object.

    Returns:
        Handler instance for the layer's type.
    """
    return get_handler(layer.type)


def list_registered_types() -> list:
    """Get list of registered layer types.

    Returns:
        List of registered layer type strings.
    """
    return list(_HANDLERS.keys())


# Register handlers when module is imported
def _register_default_handlers():
    """Register the default handlers on module load."""
    # Delayed imports to avoid circular dependencies
    try:
        from .fill_layer_handler import FillLayerHandler
        register_handler('COLOR', FillLayerHandler())
    except ImportError:
        pass

    try:
        from .paint_layer_handler import PaintLayerHandler
        register_handler('IMAGE', PaintLayerHandler())
    except ImportError:
        pass

    try:
        from .procedural_layer_handler import ProceduralLayerHandler
        register_handler('PROCEDURAL', ProceduralLayerHandler())
    except ImportError:
        pass


# Auto-register on import
_register_default_handlers()
