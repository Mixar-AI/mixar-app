# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Bake to layer operators - main module aggregating all bake-related operators.

This module re-exports all operators for backward compatibility:
- MBakeToLayer: Main operator for baking to layer
- MBakeEntityToImage: Operator for baking entity to image
- MTryToSelectBakedVertexSelect: Try to reselect baked vertex
- MRemoveBakeInfoOtherObject: Remove bake info for other object
- MRemoveBakedEntity: Remove baked layer/mask
- MRebakeBakedImages: Rebake all baked images
- MRebakeSpecificLayers: Rebake specific layers
- MToggleBakedLayerPreview: Toggle baked layer preview
- MToggleBakedChannelPreview: Toggle baked channel preview
"""

# -------------------------------------------------------------------------
# Wrapper functions with delayed imports to avoid circular imports
# -------------------------------------------------------------------------
def channel_items(self, context):
    """Wrapper for channel_items with delayed import."""
    from ...layer.helpers.layer_enum_helpers import channel_items as _impl

    return _impl(self, context)


def get_normal_map_type_items(self, context):
    """Wrapper for get_normal_map_type_items with delayed import."""
    from ...layer.helpers.layer_enum_helpers import get_normal_map_type_items as _impl

    return _impl(self, context)


# Import main operator classes from their respective modules
from .bake_to_layer_op import MBakeToLayer
from ..entity.bake_entity_to_image_op import MBakeEntityToImage

# Import utility operators
from ..operators.bake_utility_operators import (
    MTryToSelectBakedVertexSelect,
    MRemoveBakeInfoOtherObject,
    MRemoveBakedEntity,
    MRebakeBakedImages,
    MRebakeSpecificLayers,
)

# Import preview operators
from ..operators.bake_preview_operators import (
    MToggleBakedLayerPreview,
    MToggleBakedChannelPreview,
)

# Classes are registered by their respective source modules
# (bake_to_layer_op.py, bake_entity_to_image_op.py, bake_utility_operators.py, bake_preview_operators.py)
# No classes tuple here to avoid double registration by bootstrap
