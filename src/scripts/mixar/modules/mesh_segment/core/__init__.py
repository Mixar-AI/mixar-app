# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mesh Segment Core Module.

Provides mesh segment manager and mesh labeling utilities.
"""

from .mesh_segment_manager import MeshSegmentManager, get_mesh_segment_manager
from .mesh_labeler import apply_labels_to_mesh

__all__ = [
    "MeshSegmentManager",
    "get_mesh_segment_manager",
    "apply_labels_to_mesh",
]
