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
    A_CINEMA_BUTTON,
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
    A_SCENES_BUTTON,
    A_SCENES_NEW,
    A_SCENES_PANEL,
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
    # Timed to Naman's take of 2026-10-14 (4:3, shipped 960x720 @ 24 fps):
    # the delivered cut kept as is, except the silent lead-in, trimmed so
    # the first word lands at 0.8 s (2:29.2, ending on the presenter — no
    # logo card). Every enter_ms is the first word's onset minus 150 ms; a
    # gated beat's clip_end_ms is its last word + 500 ms. Onsets and line
    # ends come from the audio level (the transcript's word starts run early
    # after a pause); words inside a line from the word-level transcript.
    # Captions name the ACT and hold across its beats.
    beats=(
        Beat("intro", 0, 6090, "hero", PLACE_CENTER,
             label="Welcome",
             hide_cursor=True, hero_dim=True,
             actions=((0, "ensure_zen", {}),)),
        # -- Act 1: the viewport ("This is your viewport…" 6.24 s) -----------
        Beat("viewport", 6090, 14760, "half", PLACE_BOTTOM_LEFT,
             label="Part 1 · The viewport",
             overlays=(
                 _cursor("viewport-orbit", A_VIEWPORT, appear=7600, orbit=True),
             )),
        # "Go on, give it a spin." 14.91–16.53 s, then the tour waits.
        Beat("viewport-try", 14760, 17030, "half", PLACE_BOTTOM_LEFT,
             label="Part 1 · The viewport",
             overlays=(
                 _hint("viewport-hint",
                       "Middle-drag to orbit · scroll to zoom · Shift + middle-drag to pan",
                       A_VIEWPORT),
             ),
             gate=Gate("viewport_interacted", "shortcuts", anchor=A_VIEWPORT,
                       auto_advance_wall_ms=10000)),
        # "Click anything to select it, then G to move, R to rotate, S to
        # scale." 18.28–22.75 s. "Here are key shortcuts that will come
        # handy." 23.72–25.86 s. Each keycap row lights as it is named; the
        # rest fill in on "Here are key shortcuts".
        Beat("shortcuts", 18130, 28000, "half", PLACE_BOTTOM_LEFT,
             label="Part 1 · The viewport",
             hide_cursor=True,
             overlays=(
                 _keys("shortcut-keys", "Handy shortcuts", (
                     ("Click", "Select", 18280),
                     ("G", "Move", 19880),
                     ("R", "Rotate", 20900),
                     ("S", "Scale", 21940),
                     ("X", "Delete", 23720),
                     ("Shift+A", "Add an object", 24020),
                     ("Tab", "Edit mode", 24320),
                     ("Mod+Z", "Undo", 24620),
                     ("Shift+M", "Open Mixie", 24920),
                     ("Opt", "Push to talk (hold)", 25220),
                 ), at_pct=(80, 52), appear=18280),
             )),
        # -- Act 2: Mixie ("See the little island…" 28.15; "That's Mixie,
        # your agent." ends 31.63; "Click it to open it up." 33.12–34.40)
        # The cursor glides to the pill and rests there: the click is the
        # user's (a fake click on a gated target would read as "done").
        Beat("find-island", 28000, 34900, "half", PLACE_BOTTOM_LEFT,
             label="Part 2 · Mixie",
             actions=((28000, "island_open", {}),),
             overlays=(
                 _scribble("island-ring", A_PILL_ON_HOST, appear=28700),
                 _cursor("island-cursor", A_PILL_TOP_ON_HOST, appear=29300),
                 _hint("island-hint", "Open Mixie", A_PILL_ON_HOST, appear=31800),
             ),
             gate=Gate("island_expanded", "island-tabs", anchor=A_PILL,
                       auto_advance_wall_ms=8000,
                       auto_action=("island_expand", {}))),
        # "Mixie has tabs." 36.32 · "Agent." 38.08 · 3D 50.54 · Image 50.90 ·
        # Video 51.68 · World Model 52.26 · "and choose from a library of
        # models and tweak parameters" 53.20–55.94. The tabs named in one
        # breath flip under a moving cursor; the pane then settles on 3D
        # with its model picker ringed.
        Beat("island-tabs", 36170, 57700, "half", PLACE_BOTTOM_RIGHT,
             label="Part 2 · Mixie",
             actions=(
                 (36170, "island_expand", {}),
                 (37880, "island_tab", {"tab": "AGENT"}),
                 (50480, "island_tab", {"tab": "THREE_D"}),
                 (50840, "island_tab", {"tab": "IMAGE"}),
                 (51620, "island_tab", {"tab": "VIDEO"}),
                 (52200, "island_tab", {"tab": "SPLAT"}),
                 (53050, "island_tab", {"tab": "THREE_D"}),
             ),
             overlays=(
                 _cursor("tab-agent", A_TAB_AGENT, appear=36770, click=37880, disappear=49870),
                 _scribble("tab-agent-ring", A_TAB_AGENT, appear=37880, disappear=49870),
                 _cursor("tab-3d", A_TAB_3D, appear=49870, click=50480, disappear=50620),
                 _cursor("tab-image", A_TAB_IMAGE, appear=50620, click=50840, disappear=51320),
                 _cursor("tab-video", A_TAB_VIDEO, appear=51320, click=51620, disappear=51900),
                 _cursor("tab-splat", A_TAB_SPLAT, appear=51900, click=52200, disappear=52750),
                 _scribble("tab-splat-ring", A_TAB_SPLAT, appear=52200, disappear=52850),
                 _cursor("model-chip", A_MODEL_CHIP, appear=52750, click=53160),
                 _scribble("model-chip-ring", A_MODEL_CHIP, appear=53250),
             )),
        # "Everything you generate lands in the library." 57.85–60.16 s
        Beat("library-prompt", 57700, 60660, "half", PLACE_BOTTOM_RIGHT,
             label="Part 2 · Mixie",
             overlays=(
                 _scribble("library-ring", A_TAB_LIBRARY, appear=58050),
                 _cursor("library-cursor", A_TAB_LIBRARY, appear=58450),
                 _hint("library-hint", "Open Library", A_TAB_LIBRARY, appear=59250),
             ),
             gate=Gate("bubble_tab:GENERATIONS", "library", anchor=A_TAB_LIBRARY,
                       auto_advance_wall_ms=10000,
                       auto_action=("island_tab", {"tab": "GENERATIONS"}))),
        # "Your generations sit right here." 61.14 · "You can even link your
        # own library…" 63.65 · "…thereby saving you credits." ends 70.60.
        # The rail flips to the connected asset libraries, where "Add
        # Library…" lives, and back to the generations grid at the end of
        # the line.
        Beat("library", 60990, 72410, "half", PLACE_BOTTOM_RIGHT,
             label="Part 2 · Mixie",
             actions=(
                 (60990, "island_tab", {"tab": "GENERATIONS"}),
                 (60990, "library_source", {"source": "AI"}),
                 (63580, "library_source", {"source": "LIBRARY"}),
                 (70700, "library_source", {"source": "AI"}),
             ),
             overlays=(
                 _cursor("library-tile", A_LIBRARY_TILE, appear=61390, disappear=63010,
                         at_pct=(70, 40)),
                 _cursor("library-assets", A_LIBRARY_SOURCE_ASSETS, appear=63010,
                         click=63580, disappear=64310),
                 _cursor("library-add", A_LIBRARY_ADD, appear=64310),
                 _scribble("library-add-ring", A_LIBRARY_ADD, appear=64610),
             )),
        # -- Act 3: Scenes and Cinema Mode ------------------------------------
        # "Up in the top left is the scene drawer." 72.56 · "Every scene is
        # its own tab with its own Mixie agent." 75.00 · "So you can run
        # different tasks side by side…thereby bringing true parallelism."
        # 78.73–85.02. The cursor clicks the Scene button, the drawer slides
        # out, "+ New scene" is ringed, and the drawer closes again at the
        # end of the line.
        Beat("scenes", 72410, 86550, "half", PLACE_BOTTOM_RIGHT,
             label="Part 3 · Scenes and Cinema",
             actions=(
                 (74850, "scenes_drawer", {"open": True}),
                 (85110, "scenes_drawer", {"open": False}),
             ),
             overlays=(
                 _cursor("scenes-cursor", A_SCENES_BUTTON, appear=72710, click=74850,
                         disappear=75450),
                 _scribble("scenes-ring", A_SCENES_BUTTON, appear=73230, disappear=74850),
                 _scribble("scenes-panel-ring", A_SCENES_PANEL, appear=75350,
                           disappear=78650),
                 _cursor("scenes-new-cursor", A_SCENES_NEW, appear=78730, disappear=84900),
                 _scribble("scenes-new-ring", A_SCENES_NEW, appear=79050, disappear=84900),
             )),
        # "When you are ready to shoot, head to the Cinema Mode, which lets
        # you direct camera and build real quality production videos."
        # 86.70–93.65. A callout only: the tour never enters Cinema Mode.
        Beat("cinema", 86550, 95280, "half", PLACE_BOTTOM_RIGHT,
             label="Part 3 · Scenes and Cinema",
             overlays=(
                 _cursor("cinema-cursor", A_CINEMA_BUTTON, appear=87700),
                 _scribble("cinema-ring", A_CINEMA_BUTTON, appear=88300),
                 _callout("cinema-callout", A_CINEMA_BUTTON, "Cinema Mode",
                          "Direct the camera and build video workflows.",
                          appear=89000, side="below"),
             )),
        # -- Act 4: the moodboard ("Ideas start in 2D…" 95.43; "tilde." ends 100.30)
        Beat("moodboard-prompt", 95280, 100800, "half", PLACE_BOTTOM_LEFT,
             label="Part 4 · The moodboard",
             overlays=(
                 _scribble("grip-ring", A_DRAWER_GRIP, appear=95930),
                 _cursor("grip-cursor", A_DRAWER_GRIP, appear=96430),
                 _hint("grip-hint", "Drag the Moodboard tab out · or press ~", A_DRAWER_GRIP,
                       appear=98830, side="left"),
             ),
             gate=Gate("drawer_open", "moodboard-canvas", anchor=A_DRAWER_GRIP,
                       auto_advance_wall_ms=8000,
                       auto_action=("drawer_set", {"amount": 1.0}))),
        # "It's a canvas for your reference and concepts." 101.19 · "You can
        # drop images" 104.15 · "videos" 104.90 · "sketches" 105.42 · ends 106.94
        Beat("moodboard-canvas", 101040, 108060, "half", PLACE_TOP_LEFT,
             label="Part 4 · The moodboard",
             actions=(
                 (101040, "drawer_set", {"amount": 1.0}),
                 (101660, "moodboard_add_demo_image", {}),
             ),
             overlays=(
                 _scribble("canvas-ring", A_DRAWER_PANEL, appear=101360, disappear=103300),
                 _cursor("canvas-cursor", A_MOODBOARD_MEDIA, appear=101830, orbit=True,
                         disappear=103300, at_pct=(88, 55)),
                 _cursor("tool-media", A_DRAWER_ADD_MEDIA, appear=103300, click=104150,
                         disappear=105250),
                 _scribble("tool-media-ring", A_DRAWER_ADD_MEDIA, appear=104150,
                           disappear=105350),
                 _cursor("tool-annotate", A_DRAWER_ANNOTATE, appear=105250, click=105420),
                 _scribble("tool-annotate-ring", A_DRAWER_ANNOTATE, appear=105420),
             )),
        # "You can even build node graphs for using generative models similar
        # to ComfyUI." 108.21–112.66: the template shortcuts, then the "+" menu.
        Beat("moodboard-nodes", 108060, 114630, "half", PLACE_TOP_LEFT,
             label="Part 4 · The moodboard",
             actions=((108060, "drawer_set", {"amount": 1.0}),),
             overlays=(
                 _cursor("node-template", A_NODE_TEMPLATE, appear=108420, click=109000,
                         disappear=111000),
                 _scribble("node-template-ring", A_NODE_TEMPLATE, appear=109000,
                           disappear=111100),
                 _cursor("node-menu", A_NODE_TEMPLATES_MENU, appear=111000),
                 _scribble("node-menu-ring", A_NODE_TEMPLATES_MENU, appear=111200),
             )),
        # -- Act 5: Zen vs Engine ("Right now you are in Zen mode…" 114.78;
        # "flip to Engine mode." ends 120.70)
        Beat("engine-prompt", 114630, 121200, "half", PLACE_BOTTOM_CENTER,
             label="Part 5 · Zen and Engine",
             actions=((114630, "drawer_set", {"amount": 0.0}),),
             overlays=(
                 _scribble("zen-now-ring", A_ZEN_BUTTON, appear=115600, disappear=118460),
                 _scribble("engine-ring", A_ENGINE_BUTTON, appear=118560),
                 _cursor("engine-cursor", A_ENGINE_BUTTON, appear=118960),
                 _hint("engine-hint", "Switch to Engine mode", A_ENGINE_BUTTON,
                       appear=119860),
             ),
             gate=Gate("ui_mode:PRO", "engine-mode", anchor=A_ENGINE_BUTTON,
                       auto_advance_wall_ms=8000,
                       auto_action=("ui_mode", {"mode": "PRO"}))),
        # "The full Blender workspace is right there…" 121.60 · "And Mixie
        # works in both" 127.92 · "Let's head back to Zen mode." 132.47–133.77
        Beat("engine-mode", 121450, 135460, "half", PLACE_BOTTOM_LEFT,
             label="Part 5 · Zen and Engine",
             actions=(
                 (121450, "ui_mode", {"mode": "PRO"}),
                 (133200, "ui_mode", {"mode": "AI"}),
             ),
             overlays=(
                 _scribble("engine-toolkit-ring", A_PROPERTIES_EDITOR, appear=122130,
                           disappear=127680),
                 _scribble("engine-outliner-ring", A_OUTLINER, appear=122130,
                           disappear=127680),
                 _scribble("mixie-both-ring", A_ISLAND, appear=127680, disappear=131100),
                 _cursor("zen-cursor", A_ZEN_BUTTON, appear=132190, click=133200),
                 _scribble("zen-ring", A_ZEN_BUTTON, appear=132690),
             )),
        # "We also have a creative partner program where you get inference
        # credits and become part of a tight-knit community that shapes the
        # future of AI in media." 135.61–143.69. The REAL Help menu opens
        # under its button with the Creator Program row highlighted, and a
        # callout beside the row says what it is.
        Beat("creator-program", 135460, 145080, "half", PLACE_BOTTOM_LEFT,
             label="Creator Program",
             actions=(
                 (136900, "help_menu_open", {}),
                 (143990, "help_menu_close", {}),
             ),
             overlays=(
                 _cursor("help-cursor", A_HELP_MENU, appear=135850, click=136900,
                         disappear=137140),
                 _callout("creator-callout", A_CREATOR_ROW, "Creator Program",
                          "Inference credits, and a place in the community shaping "
                          "the future of AI and 3D.",
                          footer="Help ▸ Creator Program", appear=137340),
             )),
        # "That's it. You know where everything is. Now let's make 3D
        # together." 145.23–148.39 s, then the presenter's tail to the clip's
        # end at 149.20 (no logo card). Cleanup lands at the turn after
        # "everything is"; the replay note shows under the card once the last
        # word ends, then the card fades out (END_AFTER_WALL_MS) while the
        # moodboard stays open.
        Beat("outro", 145080, 149150, "hero", PLACE_CENTER,
             label="You're all set",
             hide_cursor=True, hero_dim=True,
             actions=((146900, "tour_cleanup", {}),),
             overlays=(
                 _caption("replay-hint", "Replay any time from Help → Start tour",
                          appear=148400),
             )),
    ),
)
