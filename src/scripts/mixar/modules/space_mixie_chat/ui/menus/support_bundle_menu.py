# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Help -> Save Support Bundle... menu entry, beside Report a Bug."""

import bpy


def _draw_support_bundle_entry(self, context):
    self.layout.separator()
    self.layout.operator(
        "mixie_chat.save_support_bundle", text="Save Support Bundle...", icon='FILE_ARCHIVE')


def register():
    bpy.types.TOPBAR_MT_help.append(_draw_support_bundle_entry)


def unregister():
    bpy.types.TOPBAR_MT_help.remove(_draw_support_bundle_entry)
