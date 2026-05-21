# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Layer Node Connections

Wrapper module that imports all layer connection functionality from split files.
Split for CLAUDE.md compliance (original: 5,223 lines → 6 files).

Submodules:
- mask_connections: Mask node reconnection (130 lines)
- layer_connections_main: Main layer reconnection (3,357 lines) ⚠️ TODO: Refactor
- parallax_connections: Parallax node reconnection (586 lines)
- depth_connections: Depth layer reconnection (281 lines)
- mp_connections: MPaint node reconnection (878 lines)
- source_connections: Source node reconnection (121 lines)

Note: layer_connections_main.py contains reconnect_layer_nodes (3,331 lines), which is
a procedural function that needs future refactoring into smaller helper functions.
"""

# Import all functions from split modules to maintain backward compatibility
from ..mask.mask_connections import *
from .layer_connections_main import *
from ..parallax.parallax_connections import *
from ..utils.depth_connections import *
from ..mp.mp_connections import *
from ..utils.source_connections import *
