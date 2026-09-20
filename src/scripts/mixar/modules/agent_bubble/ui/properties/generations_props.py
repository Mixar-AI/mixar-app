# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""My Generations tab state for the agent island.

The whole pane is driven by these WindowManager properties, and every control
in the C++ pane is a stock ``wm.context_set_enum`` / ``wm.context_set_string``
/ ``wm.context_set_int`` / ``wm.context_toggle_enum`` button bound to one of
them — the same pattern as ``bubble_tab_props.py`` and the island's mode
switch. The pane owns no bespoke state operator.

WindowManager, never Scene: which library you are browsing and which tile is
selected is per-session UI state. It must not be serialised into a shared
``.blend``, and it must not participate in undo.

The identifiers below are a CONTRACT with the C++ pane
(``agent_ui_generations_data.cc`` matches on them, never on an enum index —
an index repoints the moment an item is added). Pinned by
``tests/test_agent_bubble_generations.py``.
"""

import bpy
from bpy.props import EnumProperty, IntProperty, StringProperty

#: Module-level so a writer can bump the revision without importing bpy.types
#: bookkeeping of its own — see :func:`bump_revision`.
_REVISION_PROP = "mixar_generations_revision"

SOURCE_ITEMS = (
    ('AI', "AI generations", "Everything Mixar has generated for you"),
    ('LIBRARY', "Asset Library", "Browse and connect Blender asset libraries"),
)

FILTER_ITEMS = (
    ('ALL', "All", "Every kind of generation"),
    ('THREE_D', "3D", "Meshes and other 3D assets"),
    ('IMAGE', "Image", "Generated stills"),
    ('VIDEO', "Video", "Generated videos"),
    ('SPLAT', "Splats", "Gaussian splat worlds in this file"),
)

SORT_ITEMS = (
    ('NEWEST', "Newest first", "Most recent generations first"),
    ('OLDEST', "Oldest first", "Oldest generations first"),
)

#: Every WindowManager property this module owns. The C++ pane reads exactly
#: these names, so the list is the thing a test can compare both sides against.
PROP_NAMES = (
    "mixar_generations_source",
    "mixar_generations_filter",
    "mixar_generations_sort",
    "mixar_generations_selected",
    "mixar_generations_library",
    "mixar_generations_page",
    "mixar_generations_revision",
)


def bump_revision():
    """Tell the My Generations pane an asset library changed on disk.

    Blender's asset list is a CACHE: it reads a library once and never
    notices a .blend appearing underneath it (the Asset Browser has a
    Refresh button for exactly this). So the writer signals the reader —
    ``generation_library`` calls this after archiving a generation, and the
    C++ pane clears and re-reads the list when the number changes.

    Best-effort and main-thread only; a failure just means the new asset
    shows up on the next reload.
    """
    try:
        wm = bpy.context.window_manager
        if wm is not None:
            setattr(wm, _REVISION_PROP, getattr(wm, _REVISION_PROP, 0) + 1)
    except Exception:  # noqa: BLE001 — never break an archive over a repaint
        pass


def _redraw_bubbles(_self, context):
    """Repaint every island so the grid reflects the change immediately."""
    wm = context.window_manager if context else bpy.context.window_manager
    if wm is None:
        return
    for window in wm.windows:
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type == 'AGENT_BUBBLE':
                area.tag_redraw()


def _reset_page(self, context):
    """Refiltering must land on page one.

    Staying on page 3 of a list that just shrank to one page shows an empty
    grid, and the paging chips are hidden in that state — so there would be
    nothing on screen to click back with.
    """
    if getattr(self, "mixar_generations_page", 0):
        self.mixar_generations_page = 0
    _redraw_bubbles(self, context)


def register():
    wm = bpy.types.WindowManager
    wm.mixar_generations_source = EnumProperty(
        name="Generations Source",
        description="Which collection the My Generations grid is showing",
        items=SOURCE_ITEMS,
        default='AI',
        update=_reset_page,
        options={'SKIP_SAVE'},
    )
    wm.mixar_generations_filter = EnumProperty(
        name="Generations Filter",
        description="Which kind of generation the grid is showing",
        items=FILTER_ITEMS,
        default='ALL',
        update=_reset_page,
        options={'SKIP_SAVE'},
    )
    wm.mixar_generations_sort = EnumProperty(
        name="Generations Sort",
        description="Order the My Generations grid is sorted in",
        items=SORT_ITEMS,
        default='NEWEST',
        update=_reset_page,
        options={'SKIP_SAVE'},
    )
    wm.mixar_generations_selected = StringProperty(
        name="Selected Generation",
        description="Key of the tile the detail column is describing",
        default="",
        update=_redraw_bubbles,
        options={'SKIP_SAVE'},
    )
    wm.mixar_generations_library = StringProperty(
        name="Browsed Library",
        description="Asset library the grid is limited to (empty means all)",
        default="",
        update=_reset_page,
        options={'SKIP_SAVE'},
    )
    wm.mixar_generations_revision = IntProperty(
        name="Generations Revision",
        description=(
            "Bumped when something writes into an asset library, so the pane "
            "re-reads it"
        ),
        default=0,
        update=_redraw_bubbles,
        options={'SKIP_SAVE'},
    )
    wm.mixar_generations_page = IntProperty(
        name="Generations Page",
        description="Zero-based page of the My Generations grid",
        default=0,
        min=0,
        update=_redraw_bubbles,
        options={'SKIP_SAVE'},
    )


def unregister():
    for name in PROP_NAMES:
        if hasattr(bpy.types.WindowManager, name):
            delattr(bpy.types.WindowManager, name)
