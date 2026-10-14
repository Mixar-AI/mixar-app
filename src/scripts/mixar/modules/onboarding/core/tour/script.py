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
    # Timed to Naman's take of 2026-09-28: DeepFilterNet3 (25 dB limit),
    # silences over ~0.9 s trimmed to ~0.75 s on the source's 30 fps frame
    # grid — ~1.1 s after the five lines the tour waits on, so each pause
    # lands in the silence — and the closing Mixar logo card kept whole
    # (2:17.3). Every enter_ms is the first word's onset minus 150 ms; a
    # gated beat's clip_end_ms is its last word + 500 ms. Onsets and line
    # ends come from the audio level (the transcript's word starts run early
    # after a pause); words inside a line from the word-level transcript.
    # Captions name the ACT and hold across its beats.
    beats=(
        Beat("intro", 0, 6610, "hero", PLACE_CENTER,
             label="Welcome",
             hide_cursor=True, hero_dim=True,
             actions=((0, "ensure_zen", {}),)),
        # -- Act 1: the viewport ("This is your viewport…" 6.76 s) -----------
        Beat("viewport", 6610, 15700, "half", PLACE_BOTTOM_LEFT,
             label="Part 1 · The viewport",
             overlays=(
                 _cursor("viewport-orbit", A_VIEWPORT, appear=8220, orbit=True),
             )),
        # "Go on, give it a spin." 15.85–17.16 s, then the tour waits.
        Beat("viewport-try", 15700, 17660, "half", PLACE_BOTTOM_LEFT,
             label="Part 1 · The viewport",
             overlays=(
                 _hint("viewport-hint",
                       "Middle-drag to orbit · scroll to zoom · Shift + middle-drag to pan",
                       A_VIEWPORT),
             ),
             gate=Gate("viewport_interacted", "shortcuts", anchor=A_VIEWPORT,
                       auto_advance_wall_ms=10000)),
        # "Click anything to select it, then G to move, R to rotate, S to
        # scale. Here are some shortcuts that will come handy." 18.18–25.41 s.
        # Each keycap row lights as it is named; the rest fill in on "Here
        # are some shortcuts".
        Beat("shortcuts", 18030, 25890, "half", PLACE_BOTTOM_LEFT,
             label="Part 1 · The viewport",
             hide_cursor=True,
             overlays=(
                 _keys("shortcut-keys", "Handy shortcuts", (
                     ("Click", "Select", 18180),
                     ("G", "Move", 20000),
                     ("R", "Rotate", 20980),
                     ("S", "Scale", 22000),
                     ("X", "Delete", 23420),
                     ("Shift+A", "Add an object", 23720),
                     ("Tab", "Edit mode", 24020),
                     ("Mod+Z", "Undo", 24320),
                     ("Shift+M", "Open Mixie", 24620),
                     ("Opt", "Push to talk (hold)", 24920),
                 ), at_pct=(80, 52), appear=18180),
             )),
        # -- Act 2: Mixie ("See the little island…" 26.04; "open it up." ends 31.18)
        # The cursor glides to the pill and rests there: the click is the
        # user's (a fake click on a gated target would read as "done").
        Beat("find-island", 25890, 31680, "half", PLACE_BOTTOM_LEFT,
             label="Part 2 · Mixie",
             actions=((25890, "island_open", {}),),
             overlays=(
                 _scribble("island-ring", A_PILL_ON_HOST, appear=26590),
                 _cursor("island-cursor", A_PILL_TOP_ON_HOST, appear=27190),
                 _hint("island-hint", "Open Mixie", A_PILL_ON_HOST, appear=29190),
             ),
             gate=Gate("island_expanded", "island-tabs", anchor=A_PILL,
                       auto_advance_wall_ms=8000,
                       auto_action=("island_expand", {}))),
        # "Mixie has tabs." 32.21 · Agent 33.92 · 3D 46.18 · Image 46.70 ·
        # Video 47.38 · World Model 48.08 · "to choose from a library of
        # models and tweak different parameters" 49.73–53.09. The tabs named
        # in one breath flip under a moving cursor; the pane then settles on
        # 3D with its model picker ringed.
        Beat("island-tabs", 32060, 53410, "half", PLACE_BOTTOM_RIGHT,
             label="Part 2 · Mixie",
             actions=(
                 (32060, "island_expand", {}),
                 (33720, "island_tab", {"tab": "AGENT"}),
                 (46120, "island_tab", {"tab": "THREE_D"}),
                 (46640, "island_tab", {"tab": "IMAGE"}),
                 (47320, "island_tab", {"tab": "VIDEO"}),
                 (48020, "island_tab", {"tab": "SPLAT"}),
                 (49560, "island_tab", {"tab": "THREE_D"}),
             ),
             overlays=(
                 _cursor("tab-agent", A_TAB_AGENT, appear=32660, click=33720, disappear=45510),
                 _scribble("tab-agent-ring", A_TAB_AGENT, appear=33720, disappear=45510),
                 _cursor("tab-3d", A_TAB_3D, appear=45510, click=46120, disappear=46410),
                 _cursor("tab-image", A_TAB_IMAGE, appear=46410, click=46640, disappear=47020),
                 _cursor("tab-video", A_TAB_VIDEO, appear=47020, click=47320, disappear=47720),
                 _cursor("tab-splat", A_TAB_SPLAT, appear=47720, click=48020, disappear=49260),
                 _scribble("tab-splat-ring", A_TAB_SPLAT, appear=48020, disappear=49360),
                 _cursor("model-chip", A_MODEL_CHIP, appear=49260, click=49670),
                 _scribble("model-chip-ring", A_MODEL_CHIP, appear=49760),
             )),
        # "Everything you generate lands in the library." 53.56–55.73 s
        Beat("library-prompt", 53410, 56230, "half", PLACE_BOTTOM_RIGHT,
             label="Part 2 · Mixie",
             overlays=(
                 _scribble("library-ring", A_TAB_LIBRARY, appear=53760),
                 _cursor("library-cursor", A_TAB_LIBRARY, appear=54160),
                 _hint("library-hint", "Open Library", A_TAB_LIBRARY, appear=54960),
             ),
             gate=Gate("bubble_tab:GENERATIONS", "library", anchor=A_TAB_LIBRARY,
                       auto_advance_wall_ms=10000,
                       auto_action=("island_tab", {"tab": "GENERATIONS"}))),
        # "Your generations sit right here." 56.67 · "You can even link your
        # own library…" 59.14 · "…thereby save you credits." ends 66.32. The
        # rail flips to the connected asset libraries, where "Add Library…"
        # lives, and back to the generations grid at the end of the line.
        Beat("library", 56520, 66680, "half", PLACE_BOTTOM_RIGHT,
             label="Part 2 · Mixie",
             actions=(
                 (56520, "island_tab", {"tab": "GENERATIONS"}),
                 (56520, "library_source", {"source": "AI"}),
                 (59070, "library_source", {"source": "LIBRARY"}),
                 (66420, "library_source", {"source": "AI"}),
             ),
             overlays=(
                 _cursor("library-tile", A_LIBRARY_TILE, appear=56920, disappear=58500,
                         at_pct=(70, 40)),
                 _cursor("library-assets", A_LIBRARY_SOURCE_ASSETS, appear=58500,
                         click=59070, disappear=59800),
                 _cursor("library-add", A_LIBRARY_ADD, appear=59800),
                 _scribble("library-add-ring", A_LIBRARY_ADD, appear=60100),
             )),
        # -- Act 3: Scenes and Cinema Mode ------------------------------------
        # "Up in the top left is the scenes drawer." 66.83 · "Every scene is
        # its own tab with its own Mixie agent." 69.55 · "So you can run
        # different tasks side by side…anytime." 72.98–77.01. The cursor
        # clicks the Scene button, the drawer slides out, "+ New scene" is
        # ringed, and the drawer closes again at the end of the line.
        Beat("scenes", 66680, 77490, "half", PLACE_BOTTOM_RIGHT,
             label="Part 3 · Scenes and Cinema",
             actions=(
                 (69400, "scenes_drawer", {"open": True}),
                 (77100, "scenes_drawer", {"open": False}),
             ),
             overlays=(
                 _cursor("scenes-cursor", A_SCENES_BUTTON, appear=66980, click=69400,
                         disappear=70000),
                 _scribble("scenes-ring", A_SCENES_BUTTON, appear=67500, disappear=69400),
                 _scribble("scenes-panel-ring", A_SCENES_PANEL, appear=69900,
                           disappear=72900),
                 _cursor("scenes-new-cursor", A_SCENES_NEW, appear=72980, disappear=77000),
                 _scribble("scenes-new-ring", A_SCENES_NEW, appear=73300, disappear=77000),
             )),
        # "Once you are done with your scene work, you can even go to Cinema
        # mode, which lets you direct the camera and build video workflows."
        # 77.64–84.51. A callout only: the tour never enters Cinema Mode.
        Beat("cinema", 77490, 84850, "half", PLACE_BOTTOM_RIGHT,
             label="Part 3 · Scenes and Cinema",
             overlays=(
                 _cursor("cinema-cursor", A_CINEMA_BUTTON, appear=78900),
                 _scribble("cinema-ring", A_CINEMA_BUTTON, appear=80200),
                 _callout("cinema-callout", A_CINEMA_BUTTON, "Cinema Mode",
                          "Direct the camera and build video workflows.",
                          appear=81290, side="below"),
             )),
        # -- Act 4: the moodboard ("Ideas start in 2D…" 85.00; "tilde." ends 89.86)
        Beat("moodboard-prompt", 84850, 90360, "half", PLACE_BOTTOM_LEFT,
             label="Part 4 · The moodboard",
             overlays=(
                 _scribble("grip-ring", A_DRAWER_GRIP, appear=85500),
                 _cursor("grip-cursor", A_DRAWER_GRIP, appear=86000),
                 _hint("grip-hint", "Drag the Moodboard tab out · or press ~", A_DRAWER_GRIP,
                       appear=87800, side="left"),
             ),
             gate=Gate("drawer_open", "moodboard-canvas", anchor=A_DRAWER_GRIP,
                       auto_advance_wall_ms=8000,
                       auto_action=("drawer_set", {"amount": 1.0}))),
        # "It's a canvas for reference and concepts." 90.86 · "Drop images,
        # videos" 93.50 · "sketches" 95.10 · ends 96.27
        Beat("moodboard-canvas", 90710, 96790, "half", PLACE_TOP_LEFT,
             label="Part 4 · The moodboard",
             actions=(
                 (90710, "drawer_set", {"amount": 1.0}),
                 (91330, "moodboard_add_demo_image", {}),
             ),
             overlays=(
                 _scribble("canvas-ring", A_DRAWER_PANEL, appear=91030, disappear=92850),
                 _cursor("canvas-cursor", A_MOODBOARD_MEDIA, appear=91500, orbit=True,
                         disappear=92850, at_pct=(88, 55)),
                 _cursor("tool-media", A_DRAWER_ADD_MEDIA, appear=92850, click=93500,
                         disappear=94900),
                 _scribble("tool-media-ring", A_DRAWER_ADD_MEDIA, appear=93500,
                           disappear=95000),
                 _cursor("tool-annotate", A_DRAWER_ANNOTATE, appear=94900, click=95100),
                 _scribble("tool-annotate-ring", A_DRAWER_ANNOTATE, appear=95100),
             )),
        # "You can even build node graphs for using generative models similar
        # to ComfyUI." 96.94–100.93: the template shortcuts, then the "+" menu.
        Beat("moodboard-nodes", 96790, 101530, "half", PLACE_TOP_LEFT,
             label="Part 4 · The moodboard",
             actions=((96790, "drawer_set", {"amount": 1.0}),),
             overlays=(
                 _cursor("node-template", A_NODE_TEMPLATE, appear=97150, click=97800,
                         disappear=99550),
                 _scribble("node-template-ring", A_NODE_TEMPLATE, appear=97800,
                           disappear=99650),
                 _cursor("node-menu", A_NODE_TEMPLATES_MENU, appear=99550),
                 _scribble("node-menu-ring", A_NODE_TEMPLATES_MENU, appear=99750),
             )),
        # -- Act 5: Zen vs Engine ("You are now in Zen mode…" 101.68;
        # "flip to engine mode." ends 106.84)
        Beat("engine-prompt", 101530, 107340, "half", PLACE_BOTTOM_CENTER,
             label="Part 5 · Zen and Engine",
             actions=((101530, "drawer_set", {"amount": 0.0}),),
             overlays=(
                 _scribble("zen-now-ring", A_ZEN_BUTTON, appear=102200, disappear=104600),
                 _scribble("engine-ring", A_ENGINE_BUTTON, appear=104700),
                 _cursor("engine-cursor", A_ENGINE_BUTTON, appear=105100),
                 _hint("engine-hint", "Switch to Engine mode", A_ENGINE_BUTTON,
                       appear=106000),
             ),
             gate=Gate("ui_mode:PRO", "engine-mode", anchor=A_ENGINE_BUTTON,
                       auto_advance_wall_ms=8000,
                       auto_action=("ui_mode", {"mode": "PRO"}))),
        # "The full Blender workspace is there…" 107.77 · "Mixie works in
        # both" 112.98 · "Let's head back to Zen mode." 116.56–117.57
        Beat("engine-mode", 107620, 118080, "half", PLACE_BOTTOM_LEFT,
             label="Part 5 · Zen and Engine",
             actions=(
                 (107620, "ui_mode", {"mode": "PRO"}),
                 (117300, "ui_mode", {"mode": "AI"}),
             ),
             overlays=(
                 _scribble("engine-toolkit-ring", A_PROPERTIES_EDITOR, appear=108300,
                           disappear=112500),
                 _scribble("engine-outliner-ring", A_OUTLINER, appear=108300,
                           disappear=112500),
                 _scribble("mixie-both-ring", A_ISLAND, appear=112740, disappear=115870),
                 _cursor("zen-cursor", A_ZEN_BUTTON, appear=116280, click=117300),
                 _scribble("zen-ring", A_ZEN_BUTTON, appear=116780),
             )),
        # "We are also running a creative partner program where you get
        # inference credits and become part of a tight-knit community, which
        # shapes the future of AI and 3D." 118.23–125.90. The REAL Help menu
        # opens under its button with the Creator Program row highlighted,
        # and a callout beside the row says what it is.
        Beat("creator-program", 118080, 126430, "half", PLACE_BOTTOM_LEFT,
             label="Creator Program",
             actions=(
                 (119630, "help_menu_open", {}),
                 (126200, "help_menu_close", {}),
             ),
             overlays=(
                 _cursor("help-cursor", A_HELP_MENU, appear=118470, click=119630,
                         disappear=119870),
                 _callout("creator-callout", A_CREATOR_ROW, "Creator Program",
                          "Inference credits, and a place in the community shaping "
                          "the future of AI and 3D.",
                          footer="Help ▸ Creator Program", appear=120070),
             )),
        # "That's it. You know where everything is. Now let's make 3D
        # together." 126.58–130.24 s, then the Mixar logo card to the clip's
        # end at 137.30. Cleanup lands in the pause after "everything is";
        # the replay note shows under the logo card, then the card fades out
        # (END_AFTER_WALL_MS) while the moodboard stays open.
        Beat("outro", 126430, 137250, "hero", PLACE_CENTER,
             label="You're all set",
             hide_cursor=True, hero_dim=True,
             actions=((128650, "tour_cleanup", {}),),
             overlays=(
                 _caption("replay-hint", "Replay any time from Help → Start tour",
                          appear=130300),
             )),
    ),
)
