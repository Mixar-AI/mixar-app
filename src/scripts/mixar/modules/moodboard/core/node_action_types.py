# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Append-only persisted action identities, shared with the native renderer."""

ACTION_TYPES = (
    ('IMAGE_GEN', "Generate Image", "Generate or edit an image"),
    ('VIDEO_GEN', "Generate Video", "Generate a video from image/video references"),
    ('MODEL_3D', "Generate to 3D", "Generate a 3D asset from one image"),
    ('MASK_DETAIL', "Multi Lasso Mask",
     "Generate a detailed image of a lasso-masked region of the source image"),
    # Mesh -> mesh continuations, chained off a 3D mesh node.
    ('PBR_GEN', "PBR Generation", "Texture the connected 3D mesh"),
    ('RETOPOLOGY', "Retopology", "Retopologize the connected 3D mesh"),
    ('MESH_SEGMENT', "Mesh Segmentation", "Segment the connected 3D mesh into parts"),
    ('AUTO_RIG', "Auto Rig", "Auto-rig the connected 3D mesh"),
    ('VIDEO_UPSCALE', "Upscale Video", "Upscale the connected video to 1080p, 2K or 4K"),
    # APPEND ONLY: enum persists as an index; C++ ACTION_OUTPUT_KINDS is order-pinned.
    ('WORLD_LABS', "Generate Splat", "Generate a Gaussian splat from a prompt or image"),
    ('CHARACTER_PARTS', "Character Parts", "Generate 3D parts from the connected image masks"),
    ('ASSEMBLE', "Assemble Character", "Attach generated parts to a rigged or plain body, locally"),
)
