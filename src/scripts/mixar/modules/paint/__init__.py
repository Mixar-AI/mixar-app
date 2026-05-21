# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar Paint Module

Functional texture painting backend providing:
- Layer-based material system
- Node tree management
- Texture painting and baking
- Procedural materials
- Mask and modifier systems

This module pre-registers property groups that have cross-directory
dependency ordering requirements. All other UI modules (panels, operators,
menus, UILists, etc.) are auto-discovered by bootstrap/_load_ui_modules().
"""

import bpy

try:
    from ...config.logging_config import get_logger
    logger = get_logger(__name__)
except Exception as e:
    import logging as _fallback_logging
    logger = _fallback_logging.getLogger(__name__)
    logger.warning("Failed to initialize custom logger, using default: %s", e)

# Import property modules in DEPENDENCY ORDER
# The bootstrap auto-loader sorts by directory name/depth, which can't
# capture cross-directory dependencies. These modules must be registered
# before the auto-loader processes files that reference their types via
# CollectionProperty/PointerProperty.
#
# Dependency chain:
#   MPaintModifier  (modifier/)     -> MPaintChannel.modifiers
#   MLayer chain    (layer/)        -> MPaint.layers
#   MListItem       (list_item/)    -> MPaint.list_items
#   MBakeTarget     (bake/target/)  -> MPaint.bake_targets
#   MPaint etc      (properties/)   -> ShaderNodeTree.mp, Material.mp, etc.
#   MBakeInfoProps  (bake/utils/)   -> MImageAtlasSegment.bake_info, MUDIMAtlasSegment.bake_info

try:
    from .ui.modifier import modifier_properties
    logger.debug("Imported modifier_properties")
except Exception as e:
    logger.exception("Failed to import modifier_properties")
    modifier_properties = None

try:
    from .ui.layer.properties import layer_properties as layer_layer_properties
    logger.debug("Imported layer/layer_properties")
except Exception as e:
    logger.exception("Failed to import layer/layer_properties")
    layer_layer_properties = None

try:
    from .ui.list_item import list_item_properties
    logger.debug("Imported list_item_properties")
except Exception as e:
    logger.exception("Failed to import list_item_properties")
    list_item_properties = None

try:
    from .ui.bake.bake_target import bake_target_properties
    logger.debug("Imported bake_target_properties")
except Exception as e:
    logger.exception("Failed to import bake_target_properties")
    bake_target_properties = None

try:
    from .ui.properties import root_properties
    logger.debug("Imported root_properties")
except Exception as e:
    logger.exception("Failed to import root_properties")
    root_properties = None

try:
    from .ui.bake.utils import bake_info_properties
    logger.debug("Imported bake_info_properties")
except Exception as e:
    logger.exception("Failed to import bake_info_properties")
    bake_info_properties = None

try:
    from .ui.properties import decal_properties
    logger.debug("Imported decal_properties")
except Exception as e:
    logger.exception("Failed to import decal_properties")
    decal_properties = None

try:
    from .core.handlers import decal_handlers
    logger.debug("Imported decal_handlers")
except Exception as e:
    logger.exception("Failed to import decal_handlers")
    decal_handlers = None

# Property modules that MUST be registered in this exact order.
# Everything else (ui, panels, operators, menus, UILists, image_atlas,
# udim, preferences, etc.) is auto-discovered by _load_ui_modules().
_dependency_chain = [m for m in [
    modifier_properties,       # 1. MPaintModifier (needed by MPaintChannel)
    layer_layer_properties,    # 2. MLayer chain (needed by MPaint)
    list_item_properties,      # 3. MListItem (needed by MPaint)
    bake_target_properties,    # 4. MBakeTarget (needed by MPaint)
    root_properties,           # 5. MPaint + Blender type attachments
    bake_info_properties,      # 6. MBakeInfoProps (needed by image_atlas/udim)
] if m is not None]

logger.debug("Loaded %d dependency-chain modules for pre-registration", len(_dependency_chain))


def register():
    """Pre-register property groups in dependency order.

    Only registers the property group chain that has cross-directory
    dependencies. All other modules are auto-discovered and registered
    by bootstrap/_load_ui_modules().
    """
    logger.info("Registering paint module...")

    for module in _dependency_chain:
        module_name = getattr(module, '__name__', 'unknown')
        try:
            if hasattr(module, 'register'):
                logger.debug("Registering: %s", module_name)
                module.register()
        except Exception as e:
            logger.exception("Failed to register: %s", module_name)

    # Register decal properties on Object type
    # (not auto-discovered because it attaches a PointerProperty to bpy.types.Object)
    if decal_properties is not None:
        try:
            for cls in decal_properties.classes:
                try:
                    bpy.utils.register_class(cls)
                except ValueError as e:
                    if "already registered" not in str(e):
                        raise
            if not hasattr(bpy.types.Object, 'mp_decal'):
                bpy.types.Object.mp_decal = bpy.props.PointerProperty(
                    type=decal_properties.MPaintDecalObjectProps
                )
            logger.debug("Registered Object.mp_decal")
        except Exception as e:
            logger.exception("Failed to register Object.mp_decal")

    # Register decal handlers
    if decal_handlers is not None:
        try:
            decal_handlers.register_decal_handlers()
            logger.debug("Registered decal_handlers")
        except Exception as e:
            logger.exception("Failed to register decal_handlers")

    logger.info("Paint module registered successfully")


def unregister():
    """Unregister paint module components."""
    logger.info("Unregistering paint module...")

    # Unregister decal handlers first
    if decal_handlers is not None:
        try:
            decal_handlers.unregister_decal_handlers()
        except Exception as e:
            logger.warning("Failed to unregister decal_handlers: %s", e)

    # Unregister decal properties from Object type
    if decal_properties is not None:
        try:
            if hasattr(bpy.types.Object, 'mp_decal'):
                del bpy.types.Object.mp_decal
            for cls in reversed(decal_properties.classes):
                try:
                    bpy.utils.unregister_class(cls)
                except RuntimeError:
                    pass
        except Exception as e:
            logger.warning("Failed to unregister Object.mp_decal: %s", e)

    # Unregister dependency chain in reverse order
    for module in reversed(_dependency_chain):
        try:
            if hasattr(module, 'unregister'):
                module.unregister()
                logger.debug("Unregistered: %s", getattr(module, '__name__', 'unknown'))
        except Exception as e:
            logger.warning("Failed to unregister %s: %s",
                           getattr(module, '__name__', 'unknown'), e)

    logger.info("Paint module unregistered")
