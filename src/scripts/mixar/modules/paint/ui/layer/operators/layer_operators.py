# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer operators for creating and managing paint layers.

This module serves as the main entry point for layer operators, re-exporting
operators from specialized modules:
- layer_operators_crud: Create/Read/Update/Delete operators (MNewLayer)
- layer_operators_transform: Transform/move operators (MMoveLayer)
"""

# Re-export operators from specialized modules
from .layer_operators_crud import MNewLayer
from .layer_operators_transform import MMoveLayer


# MOpenImageToOverrideLayerChannel is deprecated - the real implementation is in
# channel_override_image_ops.py as MOpenImageToOverrideChannel (same bl_idname)
# Classes are registered by their source modules (layer_operators_crud.py, layer_operators_transform.py)
# No classes tuple needed here to avoid double registration and bl_idname conflicts
