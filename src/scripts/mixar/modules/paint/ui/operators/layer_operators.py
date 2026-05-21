# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer operators for Mixar layers system - Main entry point"""

# Import all operators from split modules
from .layer_selection_ops import (
    LAYERS_OT_LayerContextMenu,
    LAYERS_OT_SelectLayer,
    LAYERS_OT_ToggleAllSelection,
    LAYERS_OT_ClearSelection,
)

from .layer_add_ops import (
    LAYERS_OT_AddFillLayer,
    LAYERS_OT_AddLayerGroup,
    LAYERS_OT_AddAdvancedLayer,
)

from .layer_paint_ops import (
    LAYERS_OT_AddPaintLayer,
)

from .layer_procedural_ops import (
    LAYERS_OT_AddProceduralLayer,
    LAYERS_MT_ProceduralLayerMenu,
    LAYERS_OT_ProceduralMaterialLibraryPopup,
    LAYERS_MT_CustomProceduralMenu,
    LAYERS_OT_AddCustomProceduralLayer,
)

from .layer_edit_ops import (
    LAYERS_OT_RemoveActiveLayer,
    LAYERS_OT_MoveLayer,
    LAYERS_OT_EditLayerMenu,
    LAYERS_OT_RenameLayerPopup,
    LAYERS_OT_ColorPickerPopup,
    LAYERS_MT_MoreOptionsMenu,
)

from .layer_group_ops import (
    LAYERS_OT_SelectedLayersMenu,
    LAYERS_OT_MoveSelectedToGroup,
)

from .layer_copy_ops import (
    LAYERS_OT_DuplicateLayer,
    LAYERS_OT_CopyLayer,
    LAYERS_OT_PasteLayer,
)

from ..layer.channel.channel_image_operators import (
    MOpenImageToOverrideChannel,
    MOpenImageToOverride1Channel,
)

from .material_ops import (
    LAYERS_OT_CreateMaterial,
    LAYERS_OT_RemoveMPaintNode,
    MATERIALS_OT_AddMaterialSlot,
    MATERIALS_OT_RemoveMaterialSlot,
    MATERIALS_OT_MoveMaterialSlot,
)

# Classes are registered by their respective source modules
# (layer_selection_ops.py, layer_add_ops.py, layer_paint_ops.py, layer_procedural_ops.py,
#  layer_edit_ops.py, layer_group_ops.py, layer_copy_ops.py, material_ops.py, channel_image_operators.py)
# No classes tuple here to avoid double registration by bootstrap


def unregister():
    """Clean up resources on unregister."""
    pass
