# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Expose MCP setup in the standard Help menu as well as operator search."""

import bpy


def draw_connect(self, context):
    self.layout.separator()
    self.layout.operator("mixar.connect_ai", icon='LINKED')


def register():
    bpy.types.TOPBAR_MT_help.append(draw_connect)


def unregister():
    bpy.types.TOPBAR_MT_help.remove(draw_connect)
