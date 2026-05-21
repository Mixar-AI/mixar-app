# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re

import bpy
from bpy.props import EnumProperty

from .transition_utils import show_transition


class MShowTransitionBump(bpy.types.Operator):
    """Use transition bump (This will affect other channels)"""

    bl_idname = "wm.m_show_transition_bump"
    bl_label = "Show Transition Bump"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        """Check if the operator can be executed.

        Args:
            cls: The class being polled.
            context: Blender context object.

        Returns:
            bool: Always True, indicating the operator can always run.
        """
        return True

    def execute(self, context):
        """Execute the transition bump operator.

        Args:
            context: Blender context object.

        Returns:
            dict: Result from show_transition function.
        """
        return show_transition(self, context, ttype="BUMP")


class MShowTransitionRamp(bpy.types.Operator):
    """Use transition ramp (Works best if there's transition bump enabled on other channel)"""

    bl_idname = "wm.m_show_transition_ramp"
    bl_label = "Show Transition Ramp"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        """Check if the operator can be executed.

        Args:
            cls: The class being polled.
            context: Blender context object.

        Returns:
            bool: Always True, indicating the operator can always run.
        """
        return True

    def execute(self, context):
        """Execute the transition ramp operator.

        Args:
            context: Blender context object.

        Returns:
            dict: Result from show_transition function.
        """
        return show_transition(self, context, ttype="RAMP")


class MShowTransitionAO(bpy.types.Operator):
    """Use transition AO (Only works if there's transition bump enabled on other channel)"""

    bl_idname = "wm.m_show_transition_ao"
    bl_label = "Show Transition AO"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        """Check if the operator can be executed.

        Args:
            cls: The class being polled.
            context: Blender context object.

        Returns:
            bool: Always True, indicating the operator can always run.
        """
        return True

    def execute(self, context):
        """Execute the transition AO operator.

        Args:
            context: Blender context object.

        Returns:
            dict: Result from show_transition function.
        """
        return show_transition(self, context, ttype="AO")


class MHideTransitionEffect(bpy.types.Operator):
    """Remove transition Effect"""

    bl_idname = "wm.m_hide_transition_effect"
    bl_label = "Hide Transition Effect"
    bl_options = {"REGISTER", "UNDO"}

    type: EnumProperty(
        name="Type",
        items=(
            ("BUMP", "Bump", ""),
            ("RAMP", "Ramp", ""),
            ("AO", "AO", ""),
        ),
        default="BUMP",
    )

    @classmethod
    def poll(cls, context):
        """Check if the operator can be executed.

        Args:
            cls: The class being polled.
            context: Blender context object.

        Returns:
            bool: Always True, indicating the operator can always run.
        """
        return True

    def execute(self, context):
        """Execute the hide transition effect operator.

        Removes the specified transition effect (BUMP, RAMP, or AO) from the
        current channel. Validates context and channel compatibility before
        disabling the effect.

        Args:
            context: Blender context object with a 'parent' attribute.

        Returns:
            dict: Blender operator return status:
                - {"CANCELLED"}: If context is invalid or channel incompatible
                - {"FINISHED"}: If transition effect was successfully disabled
        """

        if not hasattr(context, "parent"):
            self.report({"ERROR"}, "Context is incorrect!")
            return {"CANCELLED"}

        mp = context.parent.id_data.mp
        match = re.match(
            r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]", context.parent.path_from_id()
        )
        if not match:
            self.report({"ERROR"}, "Context is incorrect!")
            return {"CANCELLED"}
        layer = mp.layers[int(match.group(1))]
        root_ch = mp.channels[int(match.group(2))]
        ch = context.parent

        if self.type == "BUMP" and root_ch.type != "NORMAL":
            self.report({"ERROR"}, "Context is incorrect!")
            return {"CANCELLED"}

        if self.type != "BUMP" and root_ch.type == "NORMAL":
            self.report({"ERROR"}, "Context is incorrect!")
            return {"CANCELLED"}

        if self.type == "BUMP":
            ch.enable_transition_bump = False
            ch.show_transition_bump = False
        elif self.type == "RAMP":
            ch.enable_transition_ramp = False
            ch.show_transition_ramp = False
        else:
            ch.enable_transition_ao = False
            ch.show_transition_ao = False

        return {"FINISHED"}
