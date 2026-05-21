# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Node Validation and Checking

Wrapper module that imports all node checking functionality from split files.
Split for CLAUDE.md compliance (original: 2,895 lines → 7 files under 800 lines).

Submodules:
- check_channel_normal_nodes: Normal map channel validation
- check_channel_blend_nodes: Channel blend and parallax validation
- check_mask_nodes: Mask mix node validation
- check_layer_io_nodes: Layer I/O and main validation entry points
- check_uv_nodes: UV node validation
- check_transition_ao_ramp: Transition AO and ramp effects
- check_transition_bump: Transition bump effects
"""

# Import all functions from split modules to maintain backward compatibility
from .check_channel_normal_nodes import *
from .check_channel_blend_nodes import *
from .check_mask_nodes import *
from .check_layer_io_nodes import *
from .check_uv_nodes import *
from .check_transition_ao_ramp import *
from .check_transition_bump import *
