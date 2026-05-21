# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer editing and management operators for Mixar layers system

This module re-exports operators from split submodules for backward compatibility.
The actual implementations are in:
- layer_remove_ops.py: Layer removal operator
- layer_move_ops.py: Layer movement operator
- layer_popup_ops.py: Popup operators (edit menu, rename, color picker)
- layer_menus.py: Menu classes
"""

# Re-export all classes from split modules for backward compatibility
from .layer_remove_ops import LAYERS_OT_RemoveActiveLayer
from .layer_move_ops import LAYERS_OT_MoveLayer
from .layer_popup_ops import (
    LAYERS_OT_EditLayerMenu,
    LAYERS_OT_RenameLayerPopup,
    LAYERS_OT_ColorPickerPopup,
)
from .layer_menus import LAYERS_MT_MoreOptionsMenu

# Classes are registered by their respective source modules
# (layer_remove_ops.py, layer_move_ops.py, layer_popup_ops.py, layer_menus.py)
# No classes tuple here to avoid double registration by bootstrap
