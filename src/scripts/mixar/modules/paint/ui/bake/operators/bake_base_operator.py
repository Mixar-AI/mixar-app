# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Base operator class for baking operations"""

from bpy.props import BoolProperty, EnumProperty, IntProperty

from ....utils.blender_commons import get_user_preferences
from ....utils.constants import image_resolution_items


class BaseBakeOperator:
    """Base class for bake operators with common properties and methods"""

    bake_device: EnumProperty(
        name="Bake Device",
        description="Device to use for baking",
        items=(("GPU", "GPU Compute", ""), ("CPU", "CPU", "")),
        default="CPU",
    )

    samples: IntProperty(
        name="Bake Samples",
        description="Bake Samples, more means less jagged on generated textures",
        default=1,
        min=1,
    )

    margin: IntProperty(
        name="Bake Margin",
        description="Bake margin in pixels",
        default=5,
        subtype="PIXEL",
    )

    margin_type: EnumProperty(
        name="Margin Type",
        description="",
        items=(
            (
                "ADJACENT_FACES",
                "Adjacent Faces",
                "Use pixels from adjacent faces across UV seams.",
            ),
            ("EXTEND", "Extend", "Extend border pixels outwards"),
        ),
        default="ADJACENT_FACES",
    )

    width: IntProperty(name="Width", default=1024, min=1, max=16384)
    height: IntProperty(name="Height", default=1024, min=1, max=16384)

    image_resolution: EnumProperty(
        name="Image Resolution", items=image_resolution_items, default="1024"
    )

    use_custom_resolution: BoolProperty(
        name="Custom Resolution",
        description="Use custom Resolution to adjust the width and height individually",
        default=False,
    )

    def invoke_operator(self, context):
        mpup = get_user_preferences()

        # Set up default bake device
        if mpup.default_bake_device != "DEFAULT":
            self.bake_device = mpup.default_bake_device

        # Use user preference default image size
        if mpup.default_image_resolution == "CUSTOM":
            self.use_custom_resolution = True
            self.width = self.height = mpup.default_new_image_size
        elif mpup.default_image_resolution != "DEFAULT":
            self.image_resolution = mpup.default_image_resolution

    def check_operator(self, context):
        if not self.use_custom_resolution:
            self.height = self.width = int(self.image_resolution)

    def is_cycles_exist(self, context):
        if not hasattr(context.scene, "cycles"):
            self.report(
                {"ERROR"},
                "Cycles Render Engine need to be enabled in user preferences!",
            )
            return False
        return True
