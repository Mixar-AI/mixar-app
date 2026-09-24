# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — the Mixar intro script (the beat table itself).

Split out of ``beats.py`` (the model, anchors and validation) for size;
``beats`` re-exports ``MIXAR_INTRO``. Re-timing a new take changes only the
numbers here. No ``bpy``.
"""

from .beats import (
    Beat,
    Gate,
    Overlay,
    Tour,
    OVERLAY_CALLOUT,
    OVERLAY_CAPTION,
    OVERLAY_CURSOR,
    OVERLAY_HINT,
    OVERLAY_KEYS,
    OVERLAY_SCRIBBLE,
    PLACE_BOTTOM_CENTER,
    PLACE_BOTTOM_LEFT,
    PLACE_BOTTOM_RIGHT,
    PLACE_CENTER,
    PLACE_TOP_LEFT,
    A_CREATOR_ROW,
    A_DRAWER_ADD_MEDIA,
    A_DRAWER_ANNOTATE,
    A_DRAWER_GRIP,
    A_DRAWER_PANEL,
    A_ENGINE_BUTTON,
    A_HELP_MENU,
    A_ISLAND,
    A_LIBRARY_ADD,
    A_LIBRARY_SOURCE_ASSETS,
    A_LIBRARY_TILE,
    A_MODEL_CHIP,
    A_MOODBOARD_MEDIA,
    A_NODE_TEMPLATE,
    A_NODE_TEMPLATES_MENU,
    A_OUTLINER,
    A_PILL,
    A_PILL_ON_HOST,
    A_PILL_TOP_ON_HOST,
    A_PROPERTIES_EDITOR,
    A_TAB_3D,
    A_TAB_AGENT,
    A_TAB_IMAGE,
    A_TAB_LIBRARY,
    A_TAB_SPLAT,
    A_TAB_VIDEO,
    A_VIEWPORT,
    A_ZEN_BUTTON,
)


# ---------------------------------------------------------------------------
# The Mixar intro tour, timed to the founder recording. Re-timing a new take
# changes only the numbers below; the script and its anchors stay.
# ---------------------------------------------------------------------------

def _cursor(id_, anchor=None, appear=None, click=None, disappear=None,
            orbit=False, at_pct=None):
    return Overlay(id_, OVERLAY_CURSOR, anchor=anchor, appear_ms=appear,
                   click_ms=click, disappear_ms=disappear, orbit=orbit,
                   at_pct=at_pct)


def _scribble(id_, anchor, appear=None, disappear=None):
    return Overlay(id_, OVERLAY_SCRIBBLE, anchor=anchor, appear_ms=appear,
                   disappear_ms=disappear)


def _hint(id_, text, anchor=None, appear=None, disappear=None, at_pct=None,
          side="auto"):
    return Overlay(id_, OVERLAY_HINT, anchor=anchor, text=text,
                   appear_ms=appear, disappear_ms=disappear, at_pct=at_pct,
                   side=side)


def _caption(id_, text, appear=None, disappear=None):
    """Copy drawn under the video card by the session; never anchored."""
    return Overlay(id_, OVERLAY_CAPTION, text=text, appear_ms=appear,
                   disappear_ms=disappear)


def _callout(id_, anchor, title, text, footer="", appear=None, disappear=None,
             side="right"):
    return Overlay(id_, OVERLAY_CALLOUT, anchor=anchor, title=title, text=text,
                   footer=footer, appear_ms=appear, disappear_ms=disappear, side=side)


def _keys(id_, title, rows, at_pct, appear=None, disappear=None):
    return Overlay(id_, OVERLAY_KEYS, title=title, rows=tuple(rows), at_pct=at_pct,
                   appear_ms=appear, disappear_ms=disappear)


MIXAR_INTRO = Tour(
    id="mixar-intro",
    title="Welcome to Mixar",
    # Timed to the founder take of 2026-09-24 (Naman, colour-corrected),
    # silences over ~0.9 s trimmed to ~0.75 s on the source's frame grid
    # (2:05.4). Seconds quoted in the comments below are the uncorrected
    # edit's and run up to ~0.1 s late. Every enter_ms is the first word of that
    # line minus ~150 ms; a gated beat's clip_end_ms is the last word
    # + 500 ms so the pause lands in the natural silence (the jump then seeks
    # to the next line). Captions name the ACT and hold across its beats.
    beats=(
        Beat("intro", 0, 7590, "hero", PLACE_CENTER,
             label="Welcome",
             hide_cursor=True, hero_dim=True,
             actions=((0, "ensure_zen", {}),)),
        # -- Act 1: the viewport ("This is your viewport…" 7.74 s) -----------
        Beat("viewport", 7590, 18037, "half", PLACE_BOTTOM_LEFT,
             label="Part 1 · The viewport",
             overlays=(
                 _cursor("viewport-orbit", A_VIEWPORT, appear=9200, orbit=True),
             )),
        # "Go give it a try." 18.21–19.09 s, then the tour waits.
        Beat("viewport-try", 18037, 19567, "half", PLACE_BOTTOM_LEFT,
             label="Part 1 · The viewport",
             overlays=(
                 _hint("viewport-hint",
                       "Middle-drag to orbit · scroll to zoom · Shift + middle-drag to pan",
                       A_VIEWPORT),
             ),
             gate=Gate("viewport_interacted", "shortcuts", anchor=A_VIEWPORT,
                       auto_advance_wall_ms=10000)),
        # "Click anything to select it, then G to move, R to rotate, S to
        # scale. Here are key shortcuts that will come handy." 19.84–28.66 s.
        # Each keycap row lights as it is named; the rest fill in on "Here
        # are key shortcuts".
        Beat("shortcuts", 19643, 29650, "half", PLACE_BOTTOM_LEFT,
             label="Part 1 · The viewport",
             hide_cursor=True,
             overlays=(
                 _keys("shortcut-keys", "Handy shortcuts", (
                     ("Click", "Select", 19793),
                     ("G", "Move", 22373),
                     ("R", "Rotate", 23793),
                     ("S", "Scale", 25113),
                     ("X", "Delete", 26893),
                     ("Shift+A", "Add an object", 27173),
                     ("Tab", "Edit mode", 27493),
                     ("Mod+Z", "Undo", 27793),
                     ("Shift+M", "Open Mixie", 28093),
                     ("Opt", "Push to talk (hold)", 28393),
                 ), at_pct=(80, 52), appear=19793),
             )),
        # -- Act 2: Mixie ("See the little island…" 29.85; "open it up." ends 36.15)
        # The cursor glides to the pill and rests there: the click is the
        # user's (a fake click on a gated target would read as "done").
        Beat("find-island", 29650, 36600, "half", PLACE_BOTTOM_LEFT,
             label="Part 2 · Mixie",
             actions=((29650, "island_open", {}),),
             overlays=(
                 _scribble("island-ring", A_PILL_ON_HOST, appear=30350),
                 _cursor("island-cursor", A_PILL_TOP_ON_HOST, appear=30950),
                 _hint("island-hint", "Open Mixie", A_PILL_ON_HOST, appear=32950),
             ),
             gate=Gate("island_expanded", "island-tabs", anchor=A_PILL,
                       auto_advance_wall_ms=8000,
                       auto_action=("island_expand", {}))),
        # "Mixie has many tabs." 36.90 · Agent 39.24 · 3D 50.91 · Image 51.41 ·
        # Video 51.91 · World Model 52.71 · "choose from the library of
        # models and tweak parameters" 54.11–57.79. The tabs named in one
        # breath flip under a moving cursor; the pane then settles on 3D with
        # its model picker ringed.
        Beat("island-tabs", 36683, 58877, "half", PLACE_BOTTOM_RIGHT,
             label="Part 2 · Mixie",
             actions=(
                 (36683, "island_expand", {}),
                 (39033, "island_tab", {"tab": "AGENT"}),
                 (50847, "island_tab", {"tab": "THREE_D"}),
                 (51347, "island_tab", {"tab": "IMAGE"}),
                 (51847, "island_tab", {"tab": "VIDEO"}),
                 (52647, "island_tab", {"tab": "SPLAT"}),
                 (53937, "island_tab", {"tab": "THREE_D"}),
             ),
             overlays=(
                 _cursor("tab-agent", A_TAB_AGENT, appear=37433, click=39033, disappear=50237),
                 _scribble("tab-agent-ring", A_TAB_AGENT, appear=39033, disappear=50237),
                 _cursor("tab-3d", A_TAB_3D, appear=50237, click=50847, disappear=51137),
                 _cursor("tab-image", A_TAB_IMAGE, appear=51137, click=51347, disappear=51637),
                 _cursor("tab-video", A_TAB_VIDEO, appear=51637, click=51847, disappear=52237),
                 _cursor("tab-splat", A_TAB_SPLAT, appear=52237, click=52647, disappear=53637),
                 _scribble("tab-splat-ring", A_TAB_SPLAT, appear=52647, disappear=53737),
                 _cursor("model-chip", A_MODEL_CHIP, appear=53637, click=54047),
                 _scribble("model-chip-ring", A_MODEL_CHIP, appear=54137),
             )),
        # "Everything you generate lands in the library." 59.10–61.50 s
        Beat("library-prompt", 58877, 61927, "half", PLACE_BOTTOM_RIGHT,
             label="Part 2 · Mixie",
             overlays=(
                 _scribble("library-ring", A_TAB_LIBRARY, appear=59227),
                 _cursor("library-cursor", A_TAB_LIBRARY, appear=59627),
                 _hint("library-hint", "Open Library", A_TAB_LIBRARY, appear=60427),
             ),
             gate=Gate("bubble_tab:GENERATIONS", "library", anchor=A_TAB_LIBRARY,
                       auto_advance_wall_ms=10000,
                       auto_action=("island_tab", {"tab": "GENERATIONS"}))),
        # "Your generations sit right here." 62.25 · "You can even link your
        # own library…" 65.27 · "…thus saving you credits." ends 71.05. The
        # rail flips to the connected asset libraries, where "Add Library…"
        # lives, and back to the generations grid at the end of the line.
        Beat("library", 62030, 71570, "half", PLACE_BOTTOM_RIGHT,
             label="Part 2 · Mixie",
             actions=(
                 (62030, "island_tab", {"tab": "GENERATIONS"}),
                 (62030, "library_source", {"source": "AI"}),
                 (65200, "library_source", {"source": "LIBRARY"}),
                 (71330, "library_source", {"source": "AI"}),
             ),
             overlays=(
                 _cursor("library-tile", A_LIBRARY_TILE, appear=62430, disappear=64630,
                         at_pct=(70, 40)),
                 _cursor("library-assets", A_LIBRARY_SOURCE_ASSETS, appear=64630,
                         click=65200, disappear=65930),
                 _cursor("library-add", A_LIBRARY_ADD, appear=65930),
                 _scribble("library-add-ring", A_LIBRARY_ADD, appear=66230),
             )),
        # -- Act 3: the moodboard ("Ideas start in 2D…" 71.80; "tilde." ends 76.58)
        Beat("moodboard-prompt", 71570, 77020, "half", PLACE_BOTTOM_LEFT,
             label="Part 3 · The moodboard",
             overlays=(
                 _scribble("grip-ring", A_DRAWER_GRIP, appear=72220),
                 _cursor("grip-cursor", A_DRAWER_GRIP, appear=72720),
                 _hint("grip-hint", "Drag the Moodboard tab out · or press ~", A_DRAWER_GRIP,
                       appear=74520, side="left"),
             ),
             gate=Gate("drawer_open", "moodboard-canvas", anchor=A_DRAWER_GRIP,
                       auto_advance_wall_ms=8000,
                       auto_action=("drawer_set", {"amount": 1.0}))),
        # "It's a canvas for your reference, concepts…" 77.33 · "drop images,
        # videos" 80.91 · "sketches" 82.89 · ends 84.39
        Beat("moodboard-canvas", 77077, 84937, "half", PLACE_TOP_LEFT,
             label="Part 3 · The moodboard",
             actions=(
                 (77077, "drawer_set", {"amount": 1.0}),
                 (77697, "moodboard_add_demo_image", {}),
             ),
             overlays=(
                 _scribble("canvas-ring", A_DRAWER_PANEL, appear=77397, disappear=80397),
                 _cursor("canvas-cursor", A_MOODBOARD_MEDIA, appear=78497, orbit=True,
                         disappear=80397, at_pct=(88, 55)),
                 _cursor("tool-media", A_DRAWER_ADD_MEDIA, appear=80397, click=81047,
                         disappear=82497),
                 _scribble("tool-media-ring", A_DRAWER_ADD_MEDIA, appear=81047,
                           disappear=82597),
                 _cursor("tool-annotate", A_DRAWER_ANNOTATE, appear=82497, click=82787),
                 _scribble("tool-annotate-ring", A_DRAWER_ANNOTATE, appear=82787),
             )),
        # "You can even build node graphs for using generative models similar
        # to ComfyUI." 85.19–89.63: the template shortcuts, then the "+" menu.
        Beat("moodboard-nodes", 84937, 90130, "half", PLACE_TOP_LEFT,
             label="Part 3 · The moodboard",
             actions=((84937, "drawer_set", {"amount": 1.0}),),
             overlays=(
                 _cursor("node-template", A_NODE_TEMPLATE, appear=85297, click=86347,
                         disappear=88097),
                 _scribble("node-template-ring", A_NODE_TEMPLATE, appear=86347,
                           disappear=88197),
                 _cursor("node-menu", A_NODE_TEMPLATES_MENU, appear=88097),
                 _scribble("node-menu-ring", A_NODE_TEMPLATES_MENU, appear=88297),
             )),
        # -- Act 4: Zen vs Engine ("Right now, we are in Zen mode…" 90.38;
        # "flip to engine mode." ends 97.32)
        Beat("engine-prompt", 90130, 97720, "half", PLACE_BOTTOM_CENTER,
             label="Part 4 · Zen and Engine",
             actions=((90130, "drawer_set", {"amount": 0.0}),),
             overlays=(
                 _scribble("zen-now-ring", A_ZEN_BUTTON, appear=91800, disappear=94200),
                 _scribble("engine-ring", A_ENGINE_BUTTON, appear=94600),
                 _cursor("engine-cursor", A_ENGINE_BUTTON, appear=95000),
                 _hint("engine-hint", "Switch to Engine mode", A_ENGINE_BUTTON,
                       appear=96400),
             ),
             gate=Gate("ui_mode:PRO", "engine-mode", anchor=A_ENGINE_BUTTON,
                       auto_advance_wall_ms=8000,
                       auto_action=("ui_mode", {"mode": "PRO"}))),
        # "It has the full Blender workspace, all the panels…" 98.07 ·
        # "Mixie works in both" 106.94 · "Let's head back to Zen mode." 110.49–111.71
        Beat("engine-mode", 97817, 112217, "half", PLACE_BOTTOM_LEFT,
             label="Part 4 · Zen and Engine",
             actions=(
                 (97817, "ui_mode", {"mode": "PRO"}),
                 (111310, "ui_mode", {"mode": "AI"}),
             ),
             overlays=(
                 _scribble("engine-toolkit-ring", A_PROPERTIES_EDITOR, appear=98497,
                           disappear=105097),
                 _scribble("engine-outliner-ring", A_OUTLINER, appear=98497,
                           disappear=105097),
                 _scribble("mixie-both-ring", A_ISLAND, appear=106700, disappear=109800),
                 _cursor("zen-cursor", A_ZEN_BUTTON, appear=110210, click=111300),
                 _scribble("zen-ring", A_ZEN_BUTTON, appear=110710),
             )),
        # "We also are running a creative partner program where you get
        # inference credits, become part of the community that shapes the
        # future of AI and 3D." 112.46–120.70. The REAL Help menu opens
        # under its button with the Creator Program row highlighted, and a
        # callout beside the row says what it is.
        Beat("creator-program", 112217, 121223, "half", PLACE_BOTTOM_LEFT,
             label="Creator Program",
             actions=(
                 (113767, "help_menu_open", {}),
                 (121007, "help_menu_close", {}),
             ),
             overlays=(
                 _cursor("help-cursor", A_HELP_MENU, appear=112607, click=113767,
                         disappear=114007),
                 _callout("creator-callout", A_CREATOR_ROW, "Creator Program",
                          "Inference credits, and a place in the community shaping "
                          "the future of AI and 3D.",
                          footer="Help ▸ Creator Program", appear=114207),
             )),
        # "That's it. You know where everything is. Now let's make 3D
        # together." 121.45–124.85 s; the clip ends at 125.70. Cleanup lands
        # in the pause after "everything is", then the card fades out over
        # the replay note (END_AFTER_WALL_MS) while the moodboard stays open.
        Beat("outro", 121223, 125323, "hero", PLACE_CENTER,
             label="You're all set",
             hide_cursor=True, hero_dim=True,
             actions=((123373, "tour_cleanup", {}),),
             overlays=(
                 _caption("replay-hint", "Replay any time from Help → Start tour",
                          appear=124823),
             )),
    ),
)
