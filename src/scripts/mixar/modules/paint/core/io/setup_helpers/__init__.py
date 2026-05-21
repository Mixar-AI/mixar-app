# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer connection setup helpers.

This package contains helper modules for layer connection setup functionality.
"""

from .bump_setup import (
    setup_tangent_bitangent,
    setup_bump_process,
    setup_smooth_bump_heights,
)
from .vector_setup import (
    setup_baked_vector,
    setup_texcoord_vector,
    connect_vector_to_nodes,
)
from .rgb_alpha_setup import (
    setup_rgb_alpha_start,
    process_rgb_through_nodes,
    setup_modifier_outputs,
)
from .channel_setup import (
    setup_type_specific_nodes,
    setup_uv_neighbor_connections,
    setup_transition_bump,
    setup_height_channel,
)

__all__ = [
    # bump_setup
    "setup_tangent_bitangent",
    "setup_bump_process",
    "setup_smooth_bump_heights",
    # vector_setup
    "setup_baked_vector",
    "setup_texcoord_vector",
    "connect_vector_to_nodes",
    # rgb_alpha_setup
    "setup_rgb_alpha_start",
    "process_rgb_through_nodes",
    "setup_modifier_outputs",
    # channel_setup
    "setup_type_specific_nodes",
    "setup_uv_neighbor_connections",
    "setup_transition_bump",
    "setup_height_channel",
]
