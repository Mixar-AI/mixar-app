# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Settings for SAM3-guided character-component detail generation."""

from bpy.props import EnumProperty, StringProperty
from bpy.types import PropertyGroup

from .moodboard_enum_callbacks import (
    _get_character_component_model_items,
    _on_model_changed,
)


class MixieCharacterComponentSettings(PropertyGroup):
    """Catalog model and optional direction shared by a component batch."""

    model: EnumProperty(
        name="Detail Model",
        description="Image model used to isolate and detail selected components",
        items=_get_character_component_model_items,
        update=_on_model_changed,
    )
    instructions: StringProperty(
        name="Direction",
        description="Optional direction applied to every component in this batch",
        default="",
        maxlen=1024,
        options={'TEXTEDIT_UPDATE'},
    )
