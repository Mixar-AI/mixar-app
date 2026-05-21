# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Core IO module for Mixar texture painting.

Organized into subpackages:
- arrangements/: Layer arrangement operations
- connections/: Layer connection operations
- input_outputs/: Input/output node operations
- mp/: MPaint connections
- parallax/: Parallax operations
- mask/: Mask operations
- utils/: IO utilities

Note: Package-level imports are intentionally avoided to prevent circular imports.
Import directly from submodules, e.g.:
    from .arrangements.layer_arrangements import rearrange_layer_nodes
    from .connections.layer_connections import reconnect_layer_nodes
    from .utils.io_utils import create_link
"""
