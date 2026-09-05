# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Screenshot capture operators for Mixie Chat."""

import bpy
import os
import platform
import subprocess
import time
from bpy.types import Operator

from mixar.config.logging_config import get_logger

from ...constants import MAX_ATTACHMENTS_PER_MESSAGE
from ...core import cleanup_loaded_file_image, get_image_display_name, validate_image_file
from ...core.attachment_board_sync import mirror_attachment_to_moodboard
from ...core.image_utils import get_mixar_screenshots_dir
from ...core.ui_utils import redraw_chat_areas

logger = get_logger(__name__)


class MIXIE_CHAT_OT_capture_screenshot(Operator):
    """Capture viewport screenshot and add as pending attachment"""
    bl_idname = "mixie_chat.capture_screenshot"
    bl_label = "Capture Screenshot"
    bl_description = "Capture the current 3D viewport and attach to next message"
    bl_options = {'REGISTER'}

    def execute(self, context):
        """Capture viewport screenshot and add to pending attachments."""
        scene = context.scene

        # Check attachment limit
        pending = scene.mixie_chat_pending_attachments
        if len(pending) >= MAX_ATTACHMENTS_PER_MESSAGE:
            self.report({'WARNING'}, f"Max {MAX_ATTACHMENTS_PER_MESSAGE} attachments")
            return {'CANCELLED'}

        # Find 3D viewport
        view3d_area = None
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                view3d_area = area
                break

        if not view3d_area:
            self.report({'WARNING'}, "No 3D Viewport found")
            return {'CANCELLED'}

        # Create screenshot file inside Mixar's screenshots directory
        import glob
        screenshots_dir = get_mixar_screenshots_dir()
        timestamp = int(time.time() * 1000)  # Milliseconds for uniqueness
        screenshot_path = os.path.join(screenshots_dir, f"mixie_screenshot_{os.getpid()}_{timestamp}.png")

        # Clean up old screenshot files from this Blender session (keep last 5)
        old_screenshots = sorted(glob.glob(os.path.join(screenshots_dir, f"mixie_screenshot_{os.getpid()}_*.png")))
        for old_file in old_screenshots[:-5]:
            try:
                os.remove(old_file)
            except OSError:
                pass

        try:
            # Save current render settings
            original_filepath = scene.render.filepath
            original_resolution_x = scene.render.resolution_x
            original_resolution_y = scene.render.resolution_y

            # Set screenshot settings
            scene.render.filepath = screenshot_path

            # Get viewport dimensions
            for region in view3d_area.regions:
                if region.type == 'WINDOW':
                    scene.render.resolution_x = region.width
                    scene.render.resolution_y = region.height
                    break

            # Render screenshot using OpenGL
            bpy.ops.render.opengl(write_still=True, view_context=True)

            # Restore original settings
            scene.render.filepath = original_filepath
            scene.render.resolution_x = original_resolution_x
            scene.render.resolution_y = original_resolution_y

            # Check if file was created
            if not os.path.exists(screenshot_path):
                self.report({'ERROR'}, "Failed to create screenshot")
                return {'CANCELLED'}

            # Check for existing viewport screenshot (by display name, not path)
            # Remove old viewport screenshot if exists (we want only the latest)
            for i, att in enumerate(list(pending)):
                if att.display_name == "viewport_screenshot.png" and att.image_source == 'FILE':
                    cleanup_loaded_file_image(att.image_path)
                    pending.remove(i)
                    logger.info("Removed old viewport screenshot")
                    break

            # Add to pending attachments (the collection chat_ops reads on send)
            attachment = pending.add()
            attachment.image_path = screenshot_path
            attachment.image_source = 'FILE'
            attachment.display_name = "viewport_screenshot.png"

            mirror_attachment_to_moodboard(scene, screenshot_path, 'FILE')

            logger.info(f"Screenshot captured: {screenshot_path}")
            self.report({'INFO'}, "Viewport screenshot attached")

            _tag_chat_redraw(context)
            return {'FINISHED'}

        except Exception as e:
            logger.error(f"Failed to capture screenshot: {e}")
            self.report({'ERROR'}, f"Screenshot capture failed: {str(e)}")
            return {'CANCELLED'}


class MIXIE_CHAT_OT_send_with_screenshot(Operator):
    """Capture viewport screenshot and immediately send the message"""
    bl_idname = "mixie_chat.send_with_screenshot"
    bl_label = "Send with Screenshot"
    bl_description = "Capture viewport and send current message with screenshot attached"
    bl_options = {'REGISTER'}

    def execute(self, context):
        """Capture screenshot, then trigger message send."""
        # First capture screenshot into pending attachments
        result = bpy.ops.mixie_chat.capture_screenshot()
        if result != {'FINISHED'}:
            return result

        # Now send the message (which picks up pending attachments)
        return bpy.ops.mixie_chat.send_message()


class MIXIE_CHAT_OT_snip_image(Operator):
    """Capture arbitrary screen region using system snipping tool"""
    bl_idname = "mixie_chat.snip_image"
    bl_label = "Snip Region"
    bl_description = "Capture a screen region using system snipping tool"
    bl_options = {'REGISTER'}

    def invoke(self, context, event):
        """Launch system screenshot tool without blocking."""
        self._process = None
        self._screenshot_path = ""
        self._timer = None
        self._start_time = 0.0

        scene = context.scene

        # Check attachment limit
        pending = scene.mixie_chat_pending_attachments
        if len(pending) >= MAX_ATTACHMENTS_PER_MESSAGE:
            self.report({'WARNING'}, f"Max {MAX_ATTACHMENTS_PER_MESSAGE} attachments")
            return {'CANCELLED'}

        system = platform.system()
        screenshots_dir = get_mixar_screenshots_dir()
        self._screenshot_path = os.path.join(screenshots_dir, f"mixie_snip_{int(time.time())}.png")

        try:
            if system == 'Darwin':
                self._process = subprocess.Popen(
                    ['screencapture', '-i', self._screenshot_path]
                )
            elif system == 'Windows':
                # Windows Snip & Sketch saves to clipboard, not file — launch and return
                try:
                    os.startfile('ms-screenclip:')
                    self.report({'INFO'},
                               "Use Paste Image (Ctrl+Shift+V) to add snipped image")
                    return {'FINISHED'}
                except OSError:
                    try:
                        subprocess.Popen(['SnippingTool.exe'])
                        self.report({'INFO'},
                                   "Save snip and use Add Image to attach")
                        return {'FINISHED'}
                    except FileNotFoundError:
                        self.report({'ERROR'},
                                   "No snipping tool found. Use Add Image instead.")
                        return {'CANCELLED'}
            else:  # Linux
                try:
                    self._process = subprocess.Popen(
                        ['gnome-screenshot', '-a', '-f', self._screenshot_path]
                    )
                except FileNotFoundError:
                    try:
                        self._process = subprocess.Popen(
                            ['scrot', '-s', self._screenshot_path]
                        )
                    except FileNotFoundError:
                        self.report({'ERROR'},
                                   "No screenshot tool found (install gnome-screenshot or scrot)")
                        return {'CANCELLED'}
        except Exception as e:
            logger.error(f"Failed to launch snipping tool: {e}")
            self.report({'ERROR'}, f"Capture failed: {str(e)}")
            return {'CANCELLED'}

        # Start modal timer to poll subprocess completion
        self._start_time = time.time()
        self._timer = context.window_manager.event_timer_add(0.2, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        """Poll subprocess until it exits or times out."""
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}

        # Check timeout (60s)
        if time.time() - self._start_time > 60.0:
            self._cleanup(context)
            if self._process:
                self._process.kill()
            self.report({'WARNING'}, "Snipping timeout")
            return {'CANCELLED'}

        # Check if process has exited
        if self._process and self._process.poll() is not None:
            returncode = self._process.returncode
            self._cleanup(context)

            if returncode != 0:
                self.report({'INFO'}, "Snipping cancelled")
                return {'CANCELLED'}

            # Verify file was created
            if not os.path.exists(self._screenshot_path):
                self.report({'INFO'}, "No image captured")
                return {'CANCELLED'}

            # Validate image
            is_valid, error = validate_image_file(self._screenshot_path)
            if not is_valid:
                self.report({'ERROR'}, error)
                try:
                    os.remove(self._screenshot_path)
                except OSError:
                    pass
                return {'CANCELLED'}

            # Add to pending attachments
            pending = context.scene.mixie_chat_pending_attachments
            attachment = pending.add()
            attachment.image_path = self._screenshot_path
            attachment.image_source = 'FILE'
            attachment.display_name = os.path.basename(self._screenshot_path)

            mirror_attachment_to_moodboard(
                context.scene, self._screenshot_path, 'FILE'
            )

            logger.info(f"Snipped region saved: {self._screenshot_path}")
            self.report({'INFO'}, "Region captured")

            _tag_chat_redraw(context)
            return {'FINISHED'}

        return {'PASS_THROUGH'}

    def _cleanup(self, context):
        """Remove modal timer."""
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None


def _tag_chat_redraw(context):
    """Trigger redraw on all Mixie Chat areas."""
    redraw_chat_areas()


classes = (
    MIXIE_CHAT_OT_capture_screenshot,
    MIXIE_CHAT_OT_send_with_screenshot,
    MIXIE_CHAT_OT_snip_image,
)
