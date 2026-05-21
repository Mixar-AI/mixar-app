# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mesh Segment Properties.

Property definitions for the Mesh Segment panel.
"""

import bpy
from bpy.props import (
    BoolProperty,
    FloatProperty,
    StringProperty,
)


def register():
    """Register Mesh Segment scene properties."""
    # Job input parameters
    bpy.types.Scene.mixie_mesh_segment_description = StringProperty(
        name="Description",
        description="Description of the mesh for segmentation context",
        default="",
    )

    bpy.types.Scene.mixie_mesh_segment_expected_parts = StringProperty(
        name="Expected Parts",
        description="Comma-separated list of expected parts (e.g., 'ears,eyes,nose,mouth')",
        default="",
    )

    # Job state
    bpy.types.Scene.mixie_mesh_segment_job_id = StringProperty(
        name="Job ID",
        description="Current mesh segment job ID",
        default="",
        options={'SKIP_SAVE'},
    )

    bpy.types.Scene.mixie_mesh_segment_status = StringProperty(
        name="Status",
        description="Current job status",
        default="",
        options={'SKIP_SAVE'},
    )

    bpy.types.Scene.mixie_mesh_segment_progress = FloatProperty(
        name="Progress",
        description="Job progress (0.0 to 1.0)",
        default=0.0,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
        options={'SKIP_SAVE'},
    )

    bpy.types.Scene.mixie_mesh_segment_current_step = StringProperty(
        name="Current Step",
        description="Current processing step",
        default="",
        options={'SKIP_SAVE'},
    )

    bpy.types.Scene.mixie_mesh_segment_is_processing = BoolProperty(
        name="Is Processing",
        description="Whether a job is currently being processed",
        default=False,
        options={'SKIP_SAVE'},
    )

    bpy.types.Scene.mixie_mesh_segment_error = StringProperty(
        name="Error",
        description="Error message if job failed",
        default="",
        options={'SKIP_SAVE'},
    )

    # Result storage
    bpy.types.Scene.mixie_mesh_segment_result = StringProperty(
        name="Result",
        description="Mesh segment result (island labels)",
        default="",
    )


def unregister():
    """Unregister Mesh Segment scene properties."""
    props = [
        "mixie_mesh_segment_result",
        "mixie_mesh_segment_error",
        "mixie_mesh_segment_is_processing",
        "mixie_mesh_segment_current_step",
        "mixie_mesh_segment_progress",
        "mixie_mesh_segment_status",
        "mixie_mesh_segment_job_id",
        "mixie_mesh_segment_expected_parts",
        "mixie_mesh_segment_description",
    ]

    for prop in props:
        try:
            delattr(bpy.types.Scene, prop)
        except AttributeError:
            pass
