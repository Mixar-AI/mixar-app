# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer copy, paste, and duplicate operators for Mixar layers system.

This module serves as a coordinator that re-exports all layer copy/paste/duplicate
operators from their respective submodules.

Submodules:
- layer_duplicate_ops: Layer duplication operator
- layer_clipboard_ops: Layer copy and paste operators
"""

# Re-export duplicate operator
from .layer_duplicate_ops import LAYERS_OT_DuplicateLayer

# Re-export clipboard operators
from .layer_clipboard_ops import LAYERS_OT_CopyLayer, LAYERS_OT_PasteLayer


# Classes are registered by their respective source modules
# (layer_duplicate_ops.py, layer_clipboard_ops.py)
# No classes tuple here to avoid double registration by bootstrap


# Define __all__ for explicit exports
__all__ = [
    'LAYERS_OT_DuplicateLayer',
    'LAYERS_OT_CopyLayer',
    'LAYERS_OT_PasteLayer',
]
