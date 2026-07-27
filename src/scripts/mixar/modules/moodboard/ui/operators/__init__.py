# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard UI Operators

Collection of operators for moodboard UI interactions.
"""

from . import (
    agent_auto_rig_ops,
    agent_segment_ops,
    cancel_ops,
    imagegen_ops,
    imagegen_reference_ops,
    lookdev_ops,
    lookdev_scene_ops,
    lookdev360_ops,
    lookdev360_reference_ops,
    image_to_3d_ops,
    image_to_3d_reference_ops,
    mesh_segment_ops,
    model_gen_ops,
    retopology_gen_ops,
    scene_recon_ops,
    segment_gen_ops,
    # scene_gen_exp_ops,  # Scene Gen Experimental disabled
    sidebar_ops,
    texture_gen_ops,
    transform_modal_ops,
)

# Submodules to register.
# NOTE: agent_auto_rig_ops was added in 9b9564fd but never listed here, so
# `mixie.agent_auto_rig` was never registered and every agent auto-rig enqueue
# failed with "operator not found". Listed now alongside agent_segment_ops.
modules = (
    agent_auto_rig_ops,
    agent_segment_ops,
    cancel_ops,
    imagegen_ops,
    imagegen_reference_ops,
    lookdev_ops,
    lookdev_scene_ops,
    lookdev360_ops,
    lookdev360_reference_ops,
    image_to_3d_ops,
    image_to_3d_reference_ops,
    mesh_segment_ops,
    model_gen_ops,
    retopology_gen_ops,
    scene_recon_ops,
    segment_gen_ops,
    # scene_gen_exp_ops,  # Scene Gen Experimental disabled
    sidebar_ops,
    texture_gen_ops,
    transform_modal_ops,
)


def register():
    """Register all operator modules"""
    for module in modules:
        module.register()


def unregister():
    """Unregister all operator modules"""
    for module in reversed(modules):
        module.unregister()
