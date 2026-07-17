# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""'@' Mention Autocomplete Properties

Scene-level bridge between the C++ text-edit hooks and the Python candidate
registry (core/mention_registry.py):

  - mixie_chat_mention_query: written from C++ on every composer edit
    (interface_handlers.cc detects the "@token" at the cursor). The update
    callback below runs synchronously and fills the rest.
  - mixie_chat_mention_items / _active / _scroll / _show: read back (and
    navigated) by C++ — the footer draws the scrollable dropdown
    (mixie_chat_mention.cc) and the text-edit hooks move/accept rows.

Everything is SKIP_SAVE — mention state describes the in-flight composer,
never the saved scene.
"""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import PropertyGroup

from mixar.config.logging_config import get_logger
from ...constants import (
    MENTION_INSERT_MAXLEN,
    MENTION_MAX_ITEMS,
    MENTION_QUERY_MAXLEN,
)
from ...core.ui_utils import redraw_chat_areas

logger = get_logger(__name__)


class MixieChatMentionItem(PropertyGroup):
    """One suggestion row in the mention dropdown."""

    name: StringProperty(
        name="Name",
        description="Datablock name shown in the dropdown row",
        default="",
        maxlen=256,
    )
    kind: IntProperty(
        name="Kind",
        description="0 = object, 1 = material, 2 = asset (icons/labels in C++)",
        default=0,
    )
    insert_text: StringProperty(
        name="Insert Text",
        description="Replacement spliced over the @token on accept",
        default="",
        # C++ reads this into a MIXIE_MENTION_INSERT_SIZE (320) byte buffer.
        maxlen=MENTION_INSERT_MAXLEN,
    )


def on_mention_query_changed(self, context):
    """Recompute the suggestion list for the freshly published query.

    Runs synchronously inside the C++ RNA_property_update call, so by the
    time the text-edit hook or footer draw continues, items/show/active are
    already consistent. Must never raise — an exception here would surface
    inside Blender's UI apply path.
    """
    try:
        query = self.mixie_chat_mention_query
        items = self.mixie_chat_mention_items
        was_open = self.mixie_chat_mention_show

        items.clear()
        if not query.startswith("@"):
            # "" (or garbage) = no active token — dropdown closed.
            self.mixie_chat_mention_show = False
        else:
            from ...core.mention_registry import REGISTRY

            matches = REGISTRY.search(query[1:], self, limit=MENTION_MAX_ITEMS)
            for match in matches:
                item = items.add()
                item.name = match.name
                item.kind = match.kind
                item.insert_text = match.insert_text
            self.mixie_chat_mention_active = 0
            self.mixie_chat_mention_scroll = 0
            self.mixie_chat_mention_show = bool(matches)

        # The edited footer redraws anyway; this keeps the OTHER chat
        # surface (docked chat vs agent bubble) in sync when both are open.
        if was_open or self.mixie_chat_mention_show:
            redraw_chat_areas()
    except Exception:
        logger.debug("mention query update failed", exc_info=True)
        try:
            self.mixie_chat_mention_show = False
        except Exception:
            pass


classes = (MixieChatMentionItem,)


def register():
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            pass  # Already registered

    bpy.types.Scene.mixie_chat_mention_query = StringProperty(
        name="Mention Query",
        description="Active '@token' at the composer cursor (written from C++)",
        default="",
        maxlen=MENTION_QUERY_MAXLEN,
        options={'SKIP_SAVE', 'HIDDEN'},
        update=on_mention_query_changed,
    )
    bpy.types.Scene.mixie_chat_mention_items = CollectionProperty(
        type=MixieChatMentionItem,
        name="Mention Suggestions",
        description="Current mention dropdown rows",
        options={'SKIP_SAVE'},
    )
    bpy.types.Scene.mixie_chat_mention_active = IntProperty(
        name="Active Mention",
        description="Highlighted dropdown item (keyboard + hover)",
        default=0,
        min=0,
        options={'SKIP_SAVE', 'HIDDEN'},
    )
    bpy.types.Scene.mixie_chat_mention_scroll = IntProperty(
        name="Mention Scroll",
        description="First visible dropdown item (list scrolls when more "
                    "than the visible row count match)",
        default=0,
        min=0,
        options={'SKIP_SAVE', 'HIDDEN'},
    )
    bpy.types.Scene.mixie_chat_mention_show = BoolProperty(
        name="Show Mention Dropdown",
        description="True while the mention dropdown is visible",
        default=False,
        options={'SKIP_SAVE', 'HIDDEN'},
    )

    from ...core import mention_registry

    mention_registry.register_handlers()


def unregister():
    from ...core import mention_registry

    mention_registry.unregister_handlers()

    for attr in (
        'mixie_chat_mention_query',
        'mixie_chat_mention_items',
        'mixie_chat_mention_active',
        'mixie_chat_mention_scroll',
        'mixie_chat_mention_show',
    ):
        if hasattr(bpy.types.Scene, attr):
            delattr(bpy.types.Scene, attr)

    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except (RuntimeError, ValueError):
            pass
