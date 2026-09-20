# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Operators for managed local models (invoked from the BYOK dialog).

Thin shells over ``core/orchestrator.py`` — all threading, timers,
toasts and WM mirroring live there; the operators only validate input on
the main thread and report. ``model_id`` props are ``SKIP_SAVE`` so a
prop-less re-invoke can never replay a stale id (see the moodboard
node_id precedent).
"""

import shutil
import threading

import bpy
from bpy.props import StringProperty
from bpy.types import Operator

from mixar.config.logging_config import get_logger

from ...core import catalog, manifest, orchestrator, paths, runtime, server_supervisor

logger = get_logger(__name__)


class MIXAR_LOCAL_OT_download_model(Operator):
    """Download the local AI runtime and this model to this computer"""
    bl_idname = "mixar_local.download_model"
    bl_label = "Download Local Model"
    bl_options = {'INTERNAL'}

    model_id: StringProperty(options={'SKIP_SAVE'})

    def execute(self, context):
        ok, err = orchestrator.start_download(self.model_id)
        if not ok:
            self.report({'ERROR'}, err or "Could not start the download")
            return {'CANCELLED'}
        return {'FINISHED'}


class MIXAR_LOCAL_OT_cancel_download(Operator):
    """Cancel the local model download (partial files are kept for resume)"""
    bl_idname = "mixar_local.cancel_download"
    bl_label = "Cancel Download"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        orchestrator.cancel_download()
        return {'FINISHED'}


class MIXAR_LOCAL_OT_start_server(Operator):
    """Start the local model server on this computer"""
    bl_idname = "mixar_local.start_server"
    bl_label = "Start Local Model"
    bl_options = {'INTERNAL'}

    model_id: StringProperty(options={'SKIP_SAVE'})

    def execute(self, context):
        if catalog.get_model(self.model_id) is None:
            self.report({'ERROR'}, "Unknown local model")
            return {'CANCELLED'}
        if not runtime.model_files_present(self.model_id):
            self.report({'ERROR'}, "Download the model first")
            return {'CANCELLED'}
        if not orchestrator.start_managed(self.model_id):
            self.report({'ERROR'}, "The local model server could not start")
            return {'CANCELLED'}
        return {'FINISHED'}


class MIXAR_LOCAL_OT_stop_server(Operator):
    """Stop the local model server"""
    bl_idname = "mixar_local.stop_server"
    bl_label = "Stop Local Model"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        orchestrator.stop_managed()
        return {'FINISHED'}


class MIXAR_LOCAL_OT_remove_model(Operator):
    """Delete this model's downloaded files from this computer"""
    bl_idname = "mixar_local.remove_model"
    bl_label = "Remove Local Model"
    bl_options = {'INTERNAL'}

    model_id: StringProperty(options={'SKIP_SAVE'})

    def execute(self, context):
        model_id = self.model_id
        if catalog.get_model(model_id) is None:
            self.report({'ERROR'}, "Unknown local model")
            return {'CANCELLED'}
        if orchestrator.download_in_progress():
            self.report({'ERROR'}, "Wait for the current download to finish")
            return {'CANCELLED'}
        current = server_supervisor.current()
        if current and current.get("model_id") == model_id:
            orchestrator.stop_managed()
        manifest.set_model_files_ready(model_id, False)
        target = paths.model_dir(model_id)

        def _rm():
            # Multi-GB deletion — keep it off the main thread. No bpy here;
            # the byok item refresh happens via a zero-delay timer.
            try:
                shutil.rmtree(target, ignore_errors=True)
            finally:
                try:
                    bpy.app.timers.register(_refresh, first_interval=0.0)
                except Exception:
                    pass

        def _refresh():
            try:
                from mixar.modules.byok.core import local_provider
                local_provider.refresh_model_items()
            except Exception:
                pass
            return None

        threading.Thread(
            target=_rm, daemon=True, name="MixarLocalModelRemove"
        ).start()
        self.report({'INFO'}, "Removing downloaded model files")
        return {'FINISHED'}


classes = (
    MIXAR_LOCAL_OT_download_model,
    MIXAR_LOCAL_OT_cancel_download,
    MIXAR_LOCAL_OT_start_server,
    MIXAR_LOCAL_OT_stop_server,
    MIXAR_LOCAL_OT_remove_model,
)
