# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Operators module"""

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

logger.debug("[Operators] Starting imports...")

try:
    from . import channel_operators
    logger.debug("[Operators] Imported channel_operators")
except Exception as e:
    logger.error("[Operators] FAILED to import channel_operators: %s", e)
    channel_operators = None

try:
    from . import mask_operators
    logger.debug("[Operators] Imported mask_operators")
except Exception as e:
    logger.error("[Operators] FAILED to import mask_operators: %s", e)
    mask_operators = None

try:
    from . import layer_operators
    logger.debug("[Operators] Imported layer_operators")
except Exception as e:
    logger.error("[Operators] FAILED to import layer_operators: %s", e)
    layer_operators = None

try:
    from . import material_ops
    logger.debug("[Operators] Imported material_ops")
except Exception as e:
    logger.error("[Operators] FAILED to import material_ops: %s", e)
    material_ops = None

try:
    from . import create_material_op
    logger.debug("[Operators] Imported create_material_op")
except Exception as e:
    logger.error("[Operators] FAILED to import create_material_op: %s", e)
    create_material_op = None

try:
    from . import decal_operators
    logger.debug("[Operators] Imported decal_operators")
except Exception as e:
    logger.error("[Operators] FAILED to import decal_operators: %s", e)
    decal_operators = None

try:
    from . import layer_image_import_ops
    logger.debug("[Operators] Imported layer_image_import_ops")
except Exception as e:
    logger.error("[Operators] FAILED to import layer_image_import_ops: %s", e)
    layer_image_import_ops = None

try:
    from . import remove_channel
    logger.debug("[Operators] Imported remove_channel")
except Exception as e:
    logger.error("[Operators] FAILED to import remove_channel: %s", e)
    remove_channel = None

try:
    from . import layer_clipboard_ops
    logger.debug("[Operators] Imported layer_clipboard_ops")
except Exception as e:
    logger.error("[Operators] FAILED to import layer_clipboard_ops: %s", e)
    layer_clipboard_ops = None

try:
    from ..bake.layer import bake_to_layer_operators
    logger.debug("[Operators] Imported bake_to_layer_operators")
except Exception as e:
    logger.error("[Operators] FAILED to import bake_to_layer_operators: %s", e)
    bake_to_layer_operators = None

modules = [m for m in [channel_operators, mask_operators, layer_operators, material_ops, create_material_op, decal_operators, layer_image_import_ops, remove_channel, layer_clipboard_ops, bake_to_layer_operators] if m is not None]

logger.debug("[Operators] Loaded %s modules", len(modules))


def register():
    """Register all operator classes from modules.

    Iterates through all modules and registers their operator classes with Blender.

    This function is idempotent - safe to call multiple times.
    """
    import bpy
    logger.debug("[Operators] register() called with %s modules", len(modules))
    total_registered = 0
    for module in modules:
        module_name = getattr(module, '__name__', 'unknown')
        classes = getattr(module, 'classes', [])
        logger.debug("[Operators] Registering %s classes from %s", len(classes), module_name)
        for cls in classes:
            try:
                bpy.utils.register_class(cls)
                total_registered += 1
                logger.debug("[Operators] Registered: %s", cls.__name__)
            except ValueError as e:
                if "already registered" not in str(e):
                    logger.error("[Operators] Failed to register %s: %s", cls.__name__, e)
                    raise
                else:
                    logger.warning("[Operators] Already registered: %s", cls.__name__)
    logger.debug("[Operators] Total registered: %s", total_registered)


def unregister():
    """Unregister all operator classes from modules.

    Iterates through all modules in reverse order and unregisters their operator
    classes from Blender.
    """
    import bpy
    for module in reversed(modules):
        for cls in reversed(module.classes):
            try:
                bpy.utils.unregister_class(cls)
            except RuntimeError:
                pass  # Class not registered
