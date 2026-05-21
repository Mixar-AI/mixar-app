# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Dock Strip

Bottom footer bar showing active job progress.
Feature buttons have moved to the right Generate panel (N-panel, UI region).
"""

import bpy
from bpy.types import Header


from mixar.modules.common.utils.mixie_space_utils import MIXIE_SPACE_AVAILABLE


if MIXIE_SPACE_AVAILABLE:

    class MIXIE_HT_dock_strip(Header):
        """Dock strip with feature buttons"""
        bl_space_type = 'MIXIE'
        bl_region_type = 'FOOTER'

        def draw(self, context):
            layout = self.layout
            layout.template_running_jobs()


    classes = (
        MIXIE_HT_dock_strip,
    )

else:
    classes = ()
