# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene-bound web publish metadata.

Bound to ``bpy.types.Scene`` as ``mixar_web_publish``. Results (slug, URLs,
revision) persist in the .blend so a reopened file still knows where its site
lives. Progress fields are runtime-only mirrors of PublishState and are
deliberately not saved (annotate with SKIP_SAVE where possible).
"""

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    StringProperty,
)

_STATUS_ITEMS = (
    ("IDLE", "Idle", "Not publishing", 0),
    ("EXPORTING", "Exporting", "Preparing the scene for the web", 1),
    ("UPLOADING", "Uploading", "Uploading the scene", 2),
    ("FINALIZING", "Finalizing", "Completing the publish", 3),
    ("DONE", "Done", "Published", 4),
    ("ERROR", "Error", "Publish failed", 5),
)


class MixarWebPublishProps(bpy.types.PropertyGroup):
    # --- user inputs ------------------------------------------------------
    title: StringProperty(  # type: ignore[valid-type]
        name="Title",
        description="Public title of your 3D website",
        default="",
        maxlen=140,
    )
    description: StringProperty(  # type: ignore[valid-type]
        name="Description",
        description="Shown under the title on your 3D website",
        default="",
        maxlen=2000,
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
        default=0,
    )
    include_animation: BoolProperty(  # type: ignore[valid-type]
        name="Include Animation",
        description="Publish the scene's animation as a looping timeline",
        default=True,
    )

    # --- results (persisted with the scene) ---------------------------------
    published_scene_id: StringProperty(  # type: ignore[valid-type]
        name="Published Scene ID",
        default="",
    )
    slug: StringProperty(name="URL Slug", default="", maxlen=80)  # type: ignore[valid-type]
    share_url: StringProperty(name="Share URL", default="", maxlen=2048)  # type: ignore[valid-type]
    viewer_url: StringProperty(name="Viewer URL", default="", maxlen=2048)  # type: ignore[valid-type]
    revision: IntProperty(name="Revision", default=0)  # type: ignore[valid-type]
    last_published: StringProperty(name="Last Published", default="", maxlen=40)  # type: ignore[valid-type]

    # --- runtime progress (never saved) --------------------------------------
    status: EnumProperty(  # type: ignore[valid-type]
        name="Status",
        items=_STATUS_ITEMS,
        default="IDLE",
        options={"SKIP_SAVE"},
    )
    progress: FloatProperty(  # type: ignore[valid-type]
        name="Progress",
        subtype="FACTOR",
        min=0.0,
        max=1.0,
        default=0.0,
        options={"SKIP_SAVE"},
    )
    status_detail: StringProperty(  # type: ignore[valid-type]
        name="Detail",
        default="",
        options={"SKIP_SAVE"},
    )
    error_message: StringProperty(  # type: ignore[valid-type]
        name="Error",
        default="",
        options={"SKIP_SAVE"},
    )

    @property
    def is_published(self) -> bool:
        return bool(self.slug and self.published_scene_id)

    @property
    def is_busy(self) -> bool:
        return self.status in {"EXPORTING", "UPLOADING", "FINALIZING"}


classes = (MixarWebPublishProps,)


def register():
    for cls in classes:
        if not getattr(cls, "is_registered", False):
            bpy.utils.register_class(cls)
    bpy.types.Scene.mixar_web_publish = bpy.props.PointerProperty(
        type=MixarWebPublishProps
    )


def unregister():
    prop = getattr(bpy.types.Scene, "mixar_web_publish", None)
    if prop is not None:
        try:
            del bpy.types.Scene.mixar_web_publish
        except Exception:  # noqa: BLE001
            pass
    for cls in reversed(classes):
        if getattr(cls, "is_registered", False):
            bpy.utils.unregister_class(cls)
