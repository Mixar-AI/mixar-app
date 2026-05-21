# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Transition AO and Ramp operations.

This module re-exports functions from sub-modules for backward compatibility.
The actual implementations are in:
- transition_ao.py - Transition AO (ambient occlusion) operations
- transition_ramp.py - Transition ramp operations
- transition_bump_influence.py - Transition bump influence and falloff operations
"""

# Re-export all functions for backward compatibility
from .transition_ao import (
    check_transition_ao_nodes,
    set_transition_ao_intensity_link,
)
from .transition_bump_influence import (
    check_transition_bump_influences_to_other_channels,
    remove_transition_bump_influence_nodes_to_other_channels,
    save_transition_bump_falloff_cache,
)
from .transition_ramp import (
    check_transition_ramp_nodes,
    load_ramp,
    remove_transition_ramp_nodes,
    save_ramp,
    set_transition_ramp_nodes,
)

__all__ = [
    # Transition AO functions
    "set_transition_ao_intensity_link",
    "check_transition_ao_nodes",
    # Transition Bump Influence functions
    "save_transition_bump_falloff_cache",
    "remove_transition_bump_influence_nodes_to_other_channels",
    "check_transition_bump_influences_to_other_channels",
    # Transition Ramp functions
    "check_transition_ramp_nodes",
    "remove_transition_ramp_nodes",
    "set_transition_ramp_nodes",
    "load_ramp",
    "save_ramp",
]
