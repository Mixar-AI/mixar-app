# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Channel checking and setup for MPaint materials.

This module provides the main entry points for checking and setting up
channel-related nodes and connections. It re-exports functions from
the specialized sub-modules:
- normal_processing: Start/end processing nodes for root channels
- channel_io: Channel inputs/outputs setup
- displacement_handling: Displacement node management
"""

# Re-export main functions for backward compatibility
from .channel_io import check_all_channel_ios
from .displacement_handling import check_displacement_node
from .normal_processing import check_start_end_root_ch_nodes

__all__ = [
    "check_start_end_root_ch_nodes",
    "check_all_channel_ios",
    "check_displacement_node",
]
