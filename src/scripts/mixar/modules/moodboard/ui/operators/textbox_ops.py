# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Text Box Operators

Operators for managing text boxes in the moodboard.
"""

import bpy
from bpy.types import Operator
from bpy.props import IntProperty, StringProperty

from ...core.moodboard_utils import get_moodboard_viewport_center
from ...core.image_lifecycle import release_moodboard_image_entry
from ....common.utils.platform_utils import format_shortcut
from ...constants import (
    TEXTBOX_TEXT_DEFAULT,
    TEXTBOX_WIDTH_DEFAULT,
    TEXTBOX_HEIGHT_DEFAULT,
    TEXTBOX_FONT_SIZE_DEFAULT,
)


# Caret glyph appended to the text box while it is being edited, so there is
# clear visual feedback that typing is active.  Stripped on confirm/cancel.
_CARET = "|"

# Inline text-edit state, kept at module scope so it survives invoke->modal
# regardless of whether the operator instance is preserved.  ``value`` is the
# real (caret-free) text; the drawn text box shows ``value + _CARET``.  Only one
# text box is edited at a time.
_EDIT = {"index": -1, "value": "", "original": "", "select_all": True, "armed": False}


def _tag_mixie_redraw(context):
    for area in context.screen.areas:
        if area.type == 'MIXIE':
            area.tag_redraw()


def _find_mixie_window_region(context):
    """Return the MIXIE (moodboard) WINDOW region with a view2d, or None."""
    for area in context.screen.areas:
        if area.type != 'MIXIE':
            continue
        for region in area.regions:
            if region.type == 'WINDOW' and getattr(region, 'view2d', None):
                return region
    return None


class MIXIE_OT_moodboard_add_textbox(Operator):
    """Add a text box to the moodboard"""

    bl_idname = "mixie.moodboard_add_textbox"
    bl_label = "Add Text"
    bl_description = f"Add a text box to the moodboard ({format_shortcut('T')})"
    bl_options = {'REGISTER', 'UNDO'}

    text: StringProperty(
        name="",
        description="Content of the text box",
        default="",
        options={'SKIP_SAVE'}
    )

    # Index of the sample text box being placed during the modal.
    _tb_index: int = -1
    _region = None

    def _cursor_view_coords(self, event):
        """Mouse position (window coords) in the moodboard's canvas space."""
        region = self._region
        rx = event.mouse_x - region.x
        ry = event.mouse_y - region.y
        return region.view2d.region_to_view(rx, ry)

    def _move_to(self, scene, vx, vy):
        boxes = scene.mixie_moodboard_textboxes
        if 0 <= self._tb_index < len(boxes):
            tb = boxes[self._tb_index]
            tb.position_x = vx
            tb.position_y = vy

    def invoke(self, context, event):
        scene = context.scene

        # Explicit text (e.g. agent/programmatic call) → place immediately.
        if self.text.strip():
            return self.execute(context)

        region = _find_mixie_window_region(context)
        if region is None:
            # No visible moodboard to place into: drop a sample box at 0,0.
            self.text = TEXTBOX_TEXT_DEFAULT
            return self.execute(context)

        self._region = region

        # Create a sample text box and follow the cursor until the user clicks.
        item = scene.mixie_moodboard_textboxes.add()
        item.text = TEXTBOX_TEXT_DEFAULT
        item.width = TEXTBOX_WIDTH_DEFAULT
        item.height = TEXTBOX_HEIGHT_DEFAULT
        item.font_size = TEXTBOX_FONT_SIZE_DEFAULT
        item.z_order = len(scene.mixie_moodboard_textboxes) + len(scene.mixie_moodboard_images)
        self._tb_index = len(scene.mixie_moodboard_textboxes) - 1

        # Select only the new box so it can be grabbed/edited/deleted right away.
        for tb in scene.mixie_moodboard_textboxes:
            tb.selected = False
        for img in scene.mixie_moodboard_images:
            img.selected = False
        item.selected = True

        vx, vy = self._cursor_view_coords(event)
        self._move_to(scene, vx, vy)
        _tag_mixie_redraw(context)

        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        scene = context.scene

        if event.type == 'MOUSEMOVE':
            vx, vy = self._cursor_view_coords(event)
            self._move_to(scene, vx, vy)
            _tag_mixie_redraw(context)
            return {'RUNNING_MODAL'}

        if event.type in {'LEFTMOUSE', 'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            _tag_mixie_redraw(context)
            self.report({'INFO'}, "Added text box (double-click to edit)")
            return {'FINISHED'}

        if event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            boxes = scene.mixie_moodboard_textboxes
            if 0 <= self._tb_index < len(boxes):
                boxes.remove(self._tb_index)
            _tag_mixie_redraw(context)
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def execute(self, context):
        scene = context.scene

        text = self.text.strip() or TEXTBOX_TEXT_DEFAULT
        viewport_cx, viewport_cy = get_moodboard_viewport_center()
        item = scene.mixie_moodboard_textboxes.add()
        item.text = text
        item.position_x = viewport_cx
        item.position_y = viewport_cy
        item.width = TEXTBOX_WIDTH_DEFAULT
        item.height = TEXTBOX_HEIGHT_DEFAULT
        item.font_size = TEXTBOX_FONT_SIZE_DEFAULT
        item.z_order = len(scene.mixie_moodboard_textboxes) + len(scene.mixie_moodboard_images)

        _tag_mixie_redraw(context)

        self.report({'INFO'}, "Added text box to moodboard")
        return {'FINISHED'}


class MIXIE_OT_moodboard_edit_textbox(Operator):
    """Edit text box content inline: type to replace, Enter to confirm, Esc to cancel"""

    bl_idname = "mixie.moodboard_edit_textbox"
    bl_label = "Edit Text Box"
    bl_description = "Edit the text directly — type to replace, Enter to confirm, Esc to cancel"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(
        name="Index",
        description="Index of the text box to edit",
        default=-1
    )

    text: StringProperty(
        name="Text",
        description="New text content (set to edit non-interactively)",
        default="",
        maxlen=1024,
        options={'SKIP_SAVE'},
    )

    def _resolve_index(self, scene):
        if self.index != -1:
            return self.index
        for i, textbox in enumerate(scene.mixie_moodboard_textboxes):
            if textbox.selected:
                return i
        return -1

    def invoke(self, context, event):
        scene = context.scene

        idx = self._resolve_index(scene)
        if idx == -1 or idx >= len(scene.mixie_moodboard_textboxes):
            self.report({'WARNING'}, "No text box selected")
            return {'CANCELLED'}

        # Non-interactive call (text supplied): set and finish, no modal.
        if self.text:
            scene.mixie_moodboard_textboxes[idx].text = self.text
            _tag_mixie_redraw(context)
            return {'FINISHED'}

        # Edit state lives at module scope (see _EDIT) rather than on self, so it
        # survives invoke->modal even when this operator is started from the C++
        # double-click handler (which may not preserve instance attributes).
        target = scene.mixie_moodboard_textboxes[idx]
        _EDIT["index"] = idx
        _EDIT["value"] = target.text
        _EDIT["original"] = target.text
        _EDIT["select_all"] = True  # whole text is "selected" — first key replaces it
        _EDIT["armed"] = False  # click-to-finish arms only after the mouse moves

        # Edit only this text box, and show a caret so it's clearly editable.
        for tb in scene.mixie_moodboard_textboxes:
            tb.selected = False
        target.selected = True
        target.text = _EDIT["value"] + _CARET

        _tag_mixie_redraw(context)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        boxes = context.scene.mixie_moodboard_textboxes
        idx = _EDIT["index"]
        if not (0 <= idx < len(boxes)):
            return {'CANCELLED'}
        tb = boxes[idx]

        # Arm click-to-finish only after the mouse moves, so the double-click
        # that started editing can't immediately confirm it.
        if event.type == 'MOUSEMOVE':
            _EDIT["armed"] = True
            return {'RUNNING_MODAL'}

        # Confirm: Enter/Tab, or a click once armed — strip the caret, keep value.
        if (event.type in {'RET', 'NUMPAD_ENTER', 'TAB'} and event.value == 'PRESS') or \
           (event.type == 'LEFTMOUSE' and event.value == 'PRESS' and _EDIT["armed"]):
            tb.text = _EDIT["value"]
            _tag_mixie_redraw(context)
            self.report({'INFO'}, "Text updated")
            return {'FINISHED'}

        # Cancel: restore the original text.
        if event.type == 'ESC' and event.value == 'PRESS':
            tb.text = _EDIT["original"]
            _tag_mixie_redraw(context)
            return {'CANCELLED'}

        if event.value != 'PRESS':
            return {'RUNNING_MODAL'}

        # Backspace: clear on first stroke (text was "selected"), else trim one.
        if event.type == 'BACK_SPACE':
            _EDIT["value"] = "" if _EDIT["select_all"] else _EDIT["value"][:-1]
            _EDIT["select_all"] = False
        # Paste text from the system clipboard (Ctrl/Cmd+V) into the box.
        elif event.type == 'V' and (event.ctrl or event.oskey):
            pasted = context.window_manager.clipboard or ""
            if not pasted:
                return {'RUNNING_MODAL'}
            _EDIT["value"] = pasted if _EDIT["select_all"] else (_EDIT["value"] + pasted)
            _EDIT["select_all"] = False
        else:
            # Printable character: replace the selection on the first key, else append.
            ch = event.unicode
            if not (ch and ch.isprintable()) or len(_EDIT["value"]) >= 1023:
                return {'RUNNING_MODAL'}
            _EDIT["value"] = ch if _EDIT["select_all"] else (_EDIT["value"] + ch)
            _EDIT["select_all"] = False

        # Reflect the edit with a trailing caret.
        tb.text = _EDIT["value"] + _CARET
        _tag_mixie_redraw(context)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        scene = context.scene

        idx = self._resolve_index(scene)
        if idx == -1 or idx >= len(scene.mixie_moodboard_textboxes):
            self.report({'WARNING'}, "Invalid text box index")
            return {'CANCELLED'}

        scene.mixie_moodboard_textboxes[idx].text = self.text
        _tag_mixie_redraw(context)
        self.report({'INFO'}, "Text box updated")
        return {'FINISHED'}


class MIXIE_OT_moodboard_delete(Operator):
    """Delete selected moodboard elements (images, text boxes and groups)"""

    bl_idname = "mixie.moodboard_delete"
    bl_label = "Delete Selected"
    bl_description = "Remove selected images, text boxes and groups from the moodboard"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        moodboard_images = scene.mixie_moodboard_images
        moodboard_groups = scene.mixie_moodboard_groups

        deleted_images = 0
        deleted_textboxes = 0
        deleted_groups = 0

        # First, delete selected groups (in reverse order to maintain indices)
        groups_to_remove = []
        for i in range(len(moodboard_groups) - 1, -1, -1):
            if moodboard_groups[i].selected:
                groups_to_remove.append(i)

        for group_idx in groups_to_remove:
            # Reset group_index for images in this group
            # Also shift indices for images in higher groups
            for img in moodboard_images:
                if img.group_index == group_idx:
                    img.group_index = -1
                elif img.group_index > group_idx:
                    img.group_index -= 1

            moodboard_groups.remove(group_idx)
            deleted_groups += 1

        # Delete selected images (in reverse order to maintain indices)
        indices_to_remove_img = []
        for i in range(len(moodboard_images) - 1, -1, -1):
            if moodboard_images[i].selected:
                indices_to_remove_img.append(i)

        for idx in indices_to_remove_img:
            release_moodboard_image_entry(moodboard_images[idx])
            moodboard_images.remove(idx)
            deleted_images += 1

        # Delete selected text boxes
        textboxes = scene.mixie_moodboard_textboxes
        indices_to_remove_text = []
        for i in range(len(textboxes) - 1, -1, -1):
            if textboxes[i].selected:
                indices_to_remove_text.append(i)

        for idx in indices_to_remove_text:
            textboxes.remove(idx)
            deleted_textboxes += 1

        if deleted_images == 0 and deleted_textboxes == 0 and deleted_groups == 0:
            self.report({'WARNING'}, "No elements selected")
            return {'CANCELLED'}

        # Trigger immediate redraw
        if context.area:
            context.area.tag_redraw()
        # Force region redraw
        if context.region:
            context.region.tag_redraw()

        # Build report message
        parts = []
        if deleted_images > 0:
            parts.append(f"{deleted_images} image(s)")
        if deleted_textboxes > 0:
            parts.append(f"{deleted_textboxes} text box(es)")
        if deleted_groups > 0:
            parts.append(f"{deleted_groups} group(s)")
        self.report({'INFO'}, f"Deleted {', '.join(parts)}")
        return {'FINISHED'}


class MIXIE_OT_moodboard_update_textbox_properties(Operator):
    """Update text box formatting properties (font size, colors, alignment, etc.)"""

    bl_idname = "mixie.moodboard_update_textbox_properties"
    bl_label = "Text Properties"
    bl_description = "Update formatting properties of the selected text box"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(
        name="Index",
        description="Index of the text box to update",
        default=-1,
        options={'SKIP_SAVE'},
    )

    def invoke(self, context, event):
        scene = context.scene

        # Resolve index from selection if not provided
        if self.index == -1:
            for i, textbox in enumerate(scene.mixie_moodboard_textboxes):
                if textbox.selected:
                    self.index = i
                    break

        if self.index == -1 or self.index >= len(scene.mixie_moodboard_textboxes):
            self.report({'WARNING'}, "No text box selected")
            return {'CANCELLED'}

        return context.window_manager.invoke_popup(self, width=320)

    def draw(self, context):
        scene = context.scene
        if self.index < 0 or self.index >= len(scene.mixie_moodboard_textboxes):
            return

        tb = scene.mixie_moodboard_textboxes[self.index]
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        col = layout.column(align=False)
        col.prop(tb, "font_size")
        col.separator(factor=0.4)

        col.prop(tb, "align")
        col.separator(factor=0.4)

        row = col.row(align=True)
        row.prop(tb, "bold", toggle=True)
        row.prop(tb, "italic", toggle=True)
        col.separator(factor=0.4)

        col.prop(tb, "text_color")
        col.prop(tb, "background_color")
        col.separator(factor=0.4)

        col.prop(tb, "width")
        col.prop(tb, "height")
        col.prop(tb, "rotation")

    def execute(self, context):
        return {'FINISHED'}


classes = (
    MIXIE_OT_moodboard_add_textbox,
    MIXIE_OT_moodboard_edit_textbox,
    MIXIE_OT_moodboard_update_textbox_properties,
    MIXIE_OT_moodboard_delete,
)
