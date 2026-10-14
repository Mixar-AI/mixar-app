# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Publish to Web properties.

``Scene.mixar_web_publish`` holds the user's inputs and the published
site's identity (id, slug, URLs, revision) — saved in the .blend so a
reopened file still knows where its site lives. Progress is process-wide
runtime state and lives on the WindowManager (never saved): a file saved
mid-upload must not reopen "busy".
"""

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

from mixar.modules.web_publish.constants import DESCRIPTION_MAX_LENGTH, TITLE_MAX_LENGTH

_STATUS_ITEMS = (
    ("IDLE", "Idle", "Not publishing", 0),
    ("EXPORTING", "Exporting", "Preparing the scene for the web", 1),
    ("UPLOADING", "Uploading", "Uploading the scene", 2),
    ("FINALIZING", "Finalizing", "Completing the publish", 3),
    ("DONE", "Done", "Published", 4),
    ("ERROR", "Error", "Publish failed", 5),
    ("CANCELLED", "Cancelled", "Publish cancelled", 6),
)

_WM_PROPS = ("mixar_web_publish_status", "mixar_web_publish_progress",
             "mixar_web_publish_scene")


class MixarWebPublishProps(bpy.types.PropertyGroup):
    # --- user inputs ------------------------------------------------------
    title: StringProperty(  # type: ignore[valid-type]
        name="Title",
        description="Public title of your 3D website",
        default="",
        maxlen=TITLE_MAX_LENGTH,
    )
    description: StringProperty(  # type: ignore[valid-type]
        name="Description",
        description="Shown under the title on your 3D website",
        default="",
        maxlen=DESCRIPTION_MAX_LENGTH,
    )
    visibility: EnumProperty(  # type: ignore[valid-type]
        name="Access",
        description=(
            "Public scenes can be discovered; unlisted scenes are reachable "
            "only by people you share the link with"
        ),
        items=(
            ("public", "Public", "Anyone with the link; listed in your gallery", 0),
            ("unlisted", "Unlisted", "Anyone with the link; never listed", 1),
        ),
        default="public",
    )
    include_animation: BoolProperty(  # type: ignore[valid-type]
        name="Include Animation",
        description="Publish the scene's animation as a looping timeline",
        default=True,
    )

    # --- results (persisted with the scene) ---------------------------------
    published_scene_id: StringProperty(name="Published Scene ID", default="")  # type: ignore[valid-type]
    slug: StringProperty(name="URL Slug", default="", maxlen=80)  # type: ignore[valid-type]
    share_url: StringProperty(name="Share URL", default="", maxlen=2048)  # type: ignore[valid-type]
    viewer_url: StringProperty(name="Viewer URL", default="", maxlen=2048)  # type: ignore[valid-type]
    revision: IntProperty(name="Revision", default=0)  # type: ignore[valid-type]
    last_published: StringProperty(name="Last Published", default="", maxlen=40)  # type: ignore[valid-type]

    @property
    def is_published(self) -> bool:
        return bool(self.slug and self.published_scene_id)

    @property
    def link(self) -> str:
        return self.share_url or self.viewer_url


classes = (MixarWebPublishProps,)


def register():
    for cls in classes:
        if not getattr(cls, "is_registered", False):
            bpy.utils.register_class(cls)
    bpy.types.Scene.mixar_web_publish = PointerProperty(type=MixarWebPublishProps)
    wm = bpy.types.WindowManager
    wm.mixar_web_publish_status = EnumProperty(
        name="Publish Status", items=_STATUS_ITEMS, default="IDLE", options={'SKIP_SAVE'})
    wm.mixar_web_publish_progress = FloatProperty(
        name="Publish Progress", subtype='FACTOR', min=0.0, max=1.0, default=0.0,
        options={'SKIP_SAVE'})
    wm.mixar_web_publish_scene = StringProperty(
        name="Publishing Scene", default="", options={'SKIP_SAVE'})


def unregister():
    for name in _WM_PROPS:
        try:
            delattr(bpy.types.WindowManager, name)
        except Exception:  # noqa: BLE001 — never registered / already gone
            pass
    try:
        del bpy.types.Scene.mixar_web_publish
    except Exception:  # noqa: BLE001
        pass
    for cls in reversed(classes):
        if getattr(cls, "is_registered", False):
            bpy.utils.unregister_class(cls)
