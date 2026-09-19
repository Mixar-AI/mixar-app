# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — the beat table.

One continuous founder video is cut into *beats*. A beat is pinned to a
video timestamp range and declares:

* where the video card sits (``card_variant`` / ``card_placement``);
* which **app actions** fire, and at which video ms (``actions``);
* which **overlays** draw — a fake cursor gliding to an anchor and
  "clicking", or a scribble mark around an anchor (``overlays``);
* whether the beat is an **interaction gate** (``gate``): the video pauses
  at ``clip_end_ms`` until the user performs the real action (a state
  predicate polled every tick) or a wall-clock timer runs out, in which
  case the tour performs the action itself and continues.

Anchors are semantic specs resolved at runtime by ``anchors.py`` against
the app's own widget geometry — never pixel offsets.

This module imports no ``bpy`` so the table and its helpers are testable.
"""

from dataclasses import dataclass, field
from typing import Optional

from .config import END_AFTER_WALL_MS, GATE_AUTO_ADVANCE_DEFAULT_MS, SKIP_DWELL_MS

# Overlay kinds.
OVERLAY_CURSOR = "cursor"
OVERLAY_SCRIBBLE = "scribble"
OVERLAY_HINT = "hint"

# Card placements.
PLACE_CENTER = "center"
PLACE_TOP_LEFT = "top-left"
PLACE_TOP_RIGHT = "top-right"
PLACE_BOTTOM_LEFT = "bottom-left"
PLACE_BOTTOM_RIGHT = "bottom-right"
PLACE_BOTTOM_CENTER = "bottom-center"

# ---------------------------------------------------------------------------
# Anchor specs (see anchors.resolve for the grammar).
# ---------------------------------------------------------------------------
A_VIEWPORT = {"area": "VIEW_3D", "region": "WINDOW"}
A_ISLAND = {"window_area": "AGENT_BUBBLE"}
# The resting pill (only exported while the island is minimised).
A_PILL = {"surface": "pill_cat"}
# The pill's footprint / top edge in MAIN-window pixels: its own window
# paints over everything, so its ring, hint and cursor live around it.
A_PILL_ON_HOST = {"pill_on_host": True}
A_PILL_TOP_ON_HOST = {"pill_on_host": "top"}
A_TAB_AGENT = {"op": "wm.context_set_enum", "tip": "Agent chat", "area": "AGENT_BUBBLE"}
A_TAB_3D = {"op": "wm.context_set_enum", "tip": "3D generation", "area": "AGENT_BUBBLE"}
A_TAB_MEDIA = {"op": "wm.context_set_enum", "tip": "Image and video generation",
               "area": "AGENT_BUBBLE"}
A_TAB_SPLAT = {"op": "wm.context_set_enum", "tip": "Gaussian Splat world generation",
               "area": "AGENT_BUBBLE"}
A_TAB_LIBRARY = {"op": "wm.context_set_enum",
                 "tip": "Your generations and connected asset libraries",
                 "area": "AGENT_BUBBLE"}
A_COMPOSER = {"prop": "mixie_chat_input", "area": "AGENT_BUBBLE"}
A_DRAWER_GRIP = {"surface": "moodboard_drawer_grip"}
A_DRAWER_PANEL = {"surface": "moodboard_drawer_panel"}
A_MOODBOARD_MEDIA = {"surface": "moodboard_media"}
# The drawer's vertical glass tool capsule: add media / text / annotate.
A_DRAWER_ADD_MEDIA = {"tip": "Open an image or video, or choose existing media",
                      "area": "VIEW_3D"}
A_DRAWER_TEXT = {"op": "mixie.moodboard_add_textbox", "area": "VIEW_3D"}
A_DRAWER_ANNOTATE = {"op": "mixie.moodboard_annotate_canvas", "area": "VIEW_3D"}
A_ENGINE_BUTTON = {"op": "mixar.set_ui_mode_pro"}
A_ZEN_BUTTON = {"op": "mixar.set_ui_mode_ai"}


@dataclass(frozen=True)
class Overlay:
    id: str
    kind: str
    anchor: Optional[dict] = None
    # Fallback position as a percentage of the host region when no anchor.
    at_pct: Optional[tuple] = None
    appear_ms: Optional[int] = None      # None → visible from beat entry
    disappear_ms: Optional[int] = None   # None → until the beat ends
    click_ms: Optional[int] = None       # cursor: pulse a click at this ms
    orbit: bool = False                  # cursor: circle the anchor
    text: str = ""                       # hint: the label
    side: str = "auto"                   # hint: "auto" (below/above) or "left"


@dataclass(frozen=True)
class Gate:
    """Pause at the beat's clip end until ``check`` is true."""
    check: str                            # predicate name, see actions.check
    advance_to: str                       # beat id to jump to when satisfied
    anchor: Optional[dict] = None         # the widget the user should use
    auto_advance_wall_ms: int = GATE_AUTO_ADVANCE_DEFAULT_MS
    auto_action: Optional[tuple] = None   # (name, args) run when the timer wins


@dataclass(frozen=True)
class Beat:
    id: str
    enter_ms: int
    clip_end_ms: int
    card_variant: str = "half"
    card_placement: str = PLACE_BOTTOM_LEFT
    # ((at_ms, action_name, args_dict), ...) — fired once each when the
    # clock passes at_ms while this beat is current.
    actions: tuple = ()
    overlays: tuple = ()
    gate: Optional[Gate] = None
    hide_cursor: bool = False
    hero_dim: bool = False                # dim the host region behind a hero card
    label: str = ""                       # caption drawn over the video ("Part 1 · The viewport")
    optional: bool = False                # may be dropped by build_skip_plan
    dwell_before_seek_ms: int = SKIP_DWELL_MS
    end_after_wall_ms: int = END_AFTER_WALL_MS  # terminal beat only


@dataclass(frozen=True)
class SkipRange:
    start_ms: int
    resume_ms: int
    dwell_ms: int


@dataclass(frozen=True)
class Tour:
    id: str
    beats: tuple
    title: str = ""


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------

def find_index(beats, beat_id: str) -> int:
    for i, b in enumerate(beats):
        if b.id == beat_id:
            return i
    return -1


def beat_index_at(beats, ms: int) -> int:
    """Index of the last beat whose ``enter_ms`` <= ms, or -1."""
    idx = -1
    for i, b in enumerate(beats):
        if b.enter_ms <= ms:
            idx = i
    return idx


def build_skip_plan(beats, skipped_ids=()):
    """Drop optional beats and compute the seek ranges that jump the video
    over them. Mirrors the reference tour's rules: only optional beats can be
    skipped, the terminal beat never is, and a run of skipped beats whose
    actions were dropped must resume on a beat that re-establishes state
    (has an action) or on the terminal beat.
    """
    by_id = {b.id: b for b in beats}
    for sid in skipped_ids:
        b = by_id.get(sid)
        if b is None:
            raise ValueError(f"build_skip_plan: {sid!r} is not a beat")
        if not b.optional:
            raise ValueError(f"build_skip_plan: beat {sid!r} is not optional")
    if beats and beats[-1].optional:
        raise ValueError("build_skip_plan: terminal beat must not be optional")

    skipped = set(skipped_ids)
    kept_idx = [i for i, b in enumerate(beats) if b.id not in skipped]
    kept = tuple(beats[i] for i in kept_idx)
    last = len(beats) - 1
    ranges = []
    for k in range(len(kept_idx) - 1):
        a, b = kept_idx[k], kept_idx[k + 1]
        prev, nxt = beats[a], beats[b]
        dropped_actions = any(beats[j].actions for j in range(a + 1, b))
        if dropped_actions and not nxt.actions and b != last:
            raise ValueError(
                f"build_skip_plan: skipped actions resume onto {nxt.id!r} "
                "which re-establishes no state"
            )
        end = prev.clip_end_ms
        if nxt.enter_ms - end > 1000:
            ranges.append(SkipRange(end, nxt.enter_ms, prev.dwell_before_seek_ms))
    return kept, tuple(ranges)


def validate(tour: Tour) -> None:
    """Raise ValueError on an inconsistent table (run by the tests)."""
    ids = [b.id for b in tour.beats]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate beat ids")
    prev_enter = -1
    for b in tour.beats:
        if b.enter_ms <= prev_enter:
            raise ValueError(f"{b.id}: enter_ms must increase")
        if b.clip_end_ms < b.enter_ms:
            raise ValueError(f"{b.id}: clip_end_ms before enter_ms")
        for at, name, _args in b.actions:
            if at < b.enter_ms:
                raise ValueError(f"{b.id}: action {name} fires before entry")
        if b.gate is not None:
            j = find_index(tour.beats, b.gate.advance_to)
            if j <= find_index(tour.beats, b.id):
                raise ValueError(f"{b.id}: gate must advance forward")
        prev_enter = b.enter_ms
    build_skip_plan(tour.beats, [b.id for b in tour.beats if b.optional])


# ---------------------------------------------------------------------------
# The Mixar intro tour. Timings are placeholders matching the generated
# placeholder video; re-time against the founder recording, nothing else
# changes.
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


MIXAR_INTRO = Tour(
    id="mixar-intro",
    title="Welcome to Mixar",
    # Timed to the founder take of 2026-09-18 (1:54): every enter_ms is the
    # first word of that line minus ~150 ms; a gated beat's clip_end_ms is
    # ~300 ms after its last word so the pause lands in the natural silence.
    beats=(
        Beat("intro", 0, 6700, "hero", PLACE_CENTER,
             label="Welcome",
             hide_cursor=True, hero_dim=True,
             actions=((0, "ensure_zen", {}),)),
        # -- Act 1: the viewport ("This is your viewport…" 6.9 s) ------------
        Beat("viewport", 6700, 14150, "half", PLACE_BOTTOM_LEFT,
             label="Part 1 · The viewport",
             overlays=(
                 _cursor("viewport-orbit", A_VIEWPORT, appear=8500, orbit=True),
             )),
        # "Go on, give it a spin." 14.3–16.1 s, then the tour waits.
        Beat("viewport-try", 14150, 16400, "half", PLACE_BOTTOM_LEFT,
             label="Part 1 · Try it: orbit the view",
             overlays=(
                 _hint("viewport-hint", "Drag to orbit, scroll to zoom", A_VIEWPORT),
             ),
             gate=Gate("viewport_interacted", "find-island", anchor=A_VIEWPORT,
                       auto_advance_wall_ms=12000)),
        # -- Act 2: the Agent island ("See the little island…" 18.7 s) --------
        Beat("find-island", 18570, 24700, "half", PLACE_BOTTOM_LEFT,
             label="Part 2 · Mixie, your agent",
             actions=((18570, "island_open", {}),),
             overlays=(
                 _scribble("island-ring", A_PILL_ON_HOST, appear=19500),
                 _cursor("island-cursor", A_PILL_TOP_ON_HOST, appear=20000, click=24000),
                 _hint("island-hint", "Click the island to open Mixie", A_PILL_ON_HOST,
                       appear=21000),
             ),
             gate=Gate("island_expanded", "island-tabs", anchor=A_PILL,
                       auto_advance_wall_ms=12000,
                       auto_action=("island_expand", {}))),
        # "Mixie has tabs." 27.4 s · Agent 29.0 · 3D 34.5 · Media 38.4 · Splat 42.4
        Beat("island-tabs", 27250, 47550, "card", PLACE_BOTTOM_RIGHT,
             label="Part 2 · What Mixie can do",
             actions=(
                 (27250, "island_expand", {}),
                 (29000, "island_tab", {"tab": "AGENT"}),
                 (34540, "island_tab", {"tab": "THREE_D"}),
                 (38420, "island_tab", {"tab": "MEDIA"}),
                 (42440, "island_tab", {"tab": "SPLAT"}),
             ),
             overlays=(
                 _cursor("tab-agent", A_TAB_AGENT, appear=28500, click=29000, disappear=34200),
                 _scribble("tab-agent-ring", A_TAB_AGENT, appear=29000, disappear=34200),
                 _cursor("tab-3d", A_TAB_3D, appear=34200, click=34540, disappear=38100),
                 _scribble("tab-3d-ring", A_TAB_3D, appear=34540, disappear=38100),
                 _cursor("tab-media", A_TAB_MEDIA, appear=38100, click=38420, disappear=42100),
                 _scribble("tab-media-ring", A_TAB_MEDIA, appear=38420, disappear=42100),
                 _cursor("tab-splat", A_TAB_SPLAT, appear=42100, click=42440),
                 _scribble("tab-splat-ring", A_TAB_SPLAT, appear=42440),
             )),
        # "Everything you generate lands in Library. Check it out." 47.7–52.0 s
        Beat("library-prompt", 47550, 52300, "card", PLACE_BOTTOM_RIGHT,
             label="Part 2 · Your Library",
             overlays=(
                 _scribble("library-ring", A_TAB_LIBRARY, appear=47900),
                 _cursor("library-cursor", A_TAB_LIBRARY, appear=48300),
                 _hint("library-hint", "Open Library", A_TAB_LIBRARY, appear=49500),
             ),
             gate=Gate("bubble_tab:GENERATIONS", "library", anchor=A_TAB_LIBRARY,
                       auto_advance_wall_ms=8000,
                       auto_action=("island_tab", {"tab": "GENERATIONS"}))),
        # "Your generations sit here…" 53.3 s
        Beat("library", 53190, 62590, "card", PLACE_BOTTOM_RIGHT,
             label="Part 2 · Your Library",
             actions=((53190, "island_tab", {"tab": "GENERATIONS"}),),
             overlays=(
                 _cursor("library-sweep", A_ISLAND, appear=54500, orbit=True),
             )),
        # -- Act 3: the moodboard ("Ideas start in 2D…" 62.7 s) ---------------
        Beat("moodboard-prompt", 62590, 66900, "half", PLACE_TOP_RIGHT,
             label="Part 3 · The moodboard",
             overlays=(
                 _scribble("grip-ring", A_DRAWER_GRIP, appear=63200),
                 _cursor("grip-cursor", A_DRAWER_GRIP, appear=63800),
                 _hint("grip-hint", "Pull the moodboard out", A_DRAWER_GRIP, appear=64800,
                       side="left"),
             ),
             gate=Gate("drawer_open", "moodboard-canvas", anchor=A_DRAWER_GRIP,
                       auto_advance_wall_ms=10000,
                       auto_action=("drawer_set", {"amount": 1.0}))),
        # "It's a canvas for references and concepts…" 69.2 s
        Beat("moodboard-canvas", 69090, 78890, "card", PLACE_TOP_LEFT,
             label="Part 3 · A 2D canvas for ideas",
             actions=(
                 (69090, "drawer_set", {"amount": 1.0}),
                 (69700, "moodboard_add_demo_image", {}),
             ),
             overlays=(
                 _scribble("canvas-ring", A_DRAWER_PANEL, appear=69400, disappear=72400),
                 _cursor("canvas-cursor", A_MOODBOARD_MEDIA, appear=70600, orbit=True,
                         at_pct=(88, 55)),
             )),
        # "Add images and videos from here." 79.0 · "Write notes" 81.8 · "sketch" 84.2
        Beat("moodboard-tools", 78890, 88170, "card", PLACE_TOP_LEFT,
             label="Part 3 · Moodboard tools",
             overlays=(
                 _cursor("tool-media", A_DRAWER_ADD_MEDIA, appear=78890, click=79040,
                         disappear=81700),
                 _scribble("tool-media-ring", A_DRAWER_ADD_MEDIA, appear=79040,
                           disappear=81700),
                 _hint("tool-media-hint", "Add images and video", A_DRAWER_ADD_MEDIA,
                       appear=79100, disappear=81700, side="left"),
                 _cursor("tool-text", A_DRAWER_TEXT, appear=81700, click=81820,
                         disappear=84100),
                 _scribble("tool-text-ring", A_DRAWER_TEXT, appear=81820, disappear=84100),
                 _hint("tool-text-hint", "Add notes", A_DRAWER_TEXT, appear=81900,
                       disappear=84100, side="left"),
                 _cursor("tool-annotate", A_DRAWER_ANNOTATE, appear=84100, click=84220),
                 _scribble("tool-annotate-ring", A_DRAWER_ANNOTATE, appear=84220),
                 _hint("tool-annotate-hint", "Sketch over the board", A_DRAWER_ANNOTATE,
                       appear=84300, side="left"),
             )),
        # -- Act 4: Zen vs Engine ("You are in Zen mode…" 88.3 s) --------------
        Beat("engine-prompt", 88170, 92900, "half", PLACE_BOTTOM_CENTER,
             label="Part 4 · Zen and Engine mode",
             actions=((88170, "drawer_set", {"amount": 0.0}),),
             overlays=(
                 _scribble("engine-ring", A_ENGINE_BUTTON, appear=88800),
                 _cursor("engine-cursor", A_ENGINE_BUTTON, appear=89400),
                 _hint("engine-hint", "Switch to Engine mode", A_ENGINE_BUTTON,
                       appear=91500),
             ),
             gate=Gate("ui_mode:PRO", "engine-mode", anchor=A_ENGINE_BUTTON,
                       auto_advance_wall_ms=12000,
                       auto_action=("ui_mode", {"mode": "PRO"}))),
        # "The full toolkit is there…" 95.3 s · "Let's head back to Zen." 103.0–104.0
        Beat("engine-mode", 95110, 106200, "half", PLACE_BOTTOM_CENTER,
             label="Part 4 · Engine mode",
             actions=(
                 (95110, "ui_mode", {"mode": "PRO"}),
                 (104000, "ui_mode", {"mode": "AI"}),
             ),
             overlays=(
                 _scribble("zen-ring", A_ZEN_BUTTON, appear=103000),
                 _cursor("zen-cursor", A_ZEN_BUTTON, appear=102600, click=104000),
             )),
        # "That's it. You know where everything is. Now let's make 3D
        # together." 106.4–110.0 s; the clip ends at 114.27.
        Beat("outro", 106200, 110600, "hero", PLACE_CENTER,
             label="Now let's make 3D together",
             hide_cursor=True, hero_dim=True,
             actions=((106200, "tour_cleanup", {}),)),
    ),
)
