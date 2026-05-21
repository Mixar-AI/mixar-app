# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Parallax connections module.

This module provides functions for managing parallax processing node connections.
Functions are re-exported from submodules for backward compatibility.

Submodules:
    - parallax_process_nodes: Main parallax node reconnection functionality
    - parallax_layer_nodes: Layer and iteration node connections
    - parallax_input_utils: Input connection management utilities
"""

from ......config.logging_config import get_logger
logger = get_logger(__name__)

# Re-export all public functions for backward compatibility
from .parallax_process_nodes import reconnect_parallax_process_nodes
from .parallax_layer_nodes import (
    connect_parallax_iteration,
    reconnect_parallax_layer_nodes__,
    reconnect_parallax_layer_nodes_,
)
from .parallax_input_utils import remove_all_prev_inputs

# Define __all__ for explicit public API
__all__ = [
    'reconnect_parallax_process_nodes',
    'connect_parallax_iteration',
    'reconnect_parallax_layer_nodes__',
    'reconnect_parallax_layer_nodes_',
    'remove_all_prev_inputs',
]
