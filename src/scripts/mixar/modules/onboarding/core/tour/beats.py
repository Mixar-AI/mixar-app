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
# A line of copy the session draws centred UNDER the video card (no anchor,
# no position): the outro's "replay any time" note.
OVERLAY_CAPTION = "caption"
# A box with a title, copy and a footer beside/under an anchor (the Creator
# Program row of the real Help menu the tour opens).
OVERLAY_CALLOUT = "callout"
# The shortcut panel: keycap rows that light as the narration names them.
OVERLAY_KEYS = "keys"

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
A_TAB_IMAGE = {"op": "wm.context_set_enum", "tip": "Image generation",
               "area": "AGENT_BUBBLE"}
A_TAB_VIDEO = {"op": "wm.context_set_enum", "tip": "Video generation",
               "area": "AGENT_BUBBLE"}
A_TAB_SPLAT = {"op": "wm.context_set_enum", "tip": "Gaussian Splat world generation",
               "area": "AGENT_BUBBLE"}
A_TAB_LIBRARY = {"op": "wm.context_set_enum",
                 "tip": "Your generations and connected asset libraries",
                 "area": "AGENT_BUBBLE"}
A_DRAWER_GRIP = {"surface": "moodboard_drawer_grip"}
A_DRAWER_PANEL = {"surface": "moodboard_drawer_panel"}
A_MOODBOARD_MEDIA = {"surface": "moodboard_media"}
# The drawer's tool rail: add media / annotate.
A_DRAWER_ADD_MEDIA = {"tip": "Add media or selected scene meshes", "area": "VIEW_3D"}
A_DRAWER_ANNOTATE = {"op": "mixie.moodboard_annotate_canvas", "area": "VIEW_3D"}
A_ENGINE_BUTTON = {"op": "mixar.set_ui_mode_pro"}
A_ZEN_BUTTON = {"op": "mixar.set_ui_mode_ai"}
# A generation tile in the island's Library tab (see the `library` beat).
A_LIBRARY_TILE = {"surface": "library_tile", "area": "AGENT_BUBBLE"}
# The 3D pane's model picker ("choose from the library of models").
A_MODEL_CHIP = {"tip": "AI model", "area": "AGENT_BUBBLE"}
# Library source rail: connected Blender asset libraries, and its Add button.
A_LIBRARY_SOURCE_ASSETS = {"surface": "library_source_kind", "value": "LIBRARY",
                           "area": "AGENT_BUBBLE"}
A_LIBRARY_ADD = {"op": "mixar.generations_add_library", "area": "AGENT_BUBBLE"}
# Moodboard node templates: a template shortcut and the "+" template menu.
A_NODE_TEMPLATE = {"op": "mixie.moodboard_add_template", "area": "VIEW_3D"}
A_NODE_TEMPLATES_MENU = {"tip": "Start with an editable node template", "area": "VIEW_3D"}
# The top-bar Help menu button, and the Creator Program row of the open menu.
A_HELP_MENU = {"text": "Help", "area": "TOPBAR"}
A_CREATOR_ROW = {"text": "Creator Program", "popup": True}
# Engine-mode editors the "full toolkit" line points at (inset rings).
A_PROPERTIES_EDITOR = {"area": "PROPERTIES", "region": "WINDOW"}
A_OUTLINER = {"area": "OUTLINER", "region": "WINDOW"}


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
    text: str = ""                       # hint / caption / callout body: the label
    side: str = "auto"                   # hint: "auto"/"left"; callout: "below"/"right"
    title: str = ""                      # callout / keys: the heading
    footer: str = ""                     # callout: the last line (menu path)
    rows: tuple = ()                     # keys: ((keys, label, named_ms), ...)


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
    # With every optional beat dropped, each surviving gate must still have
    # a forward target: the runner refuses a table whose gate would no-op.
    kept, _ranges = build_skip_plan(tour.beats, [b.id for b in tour.beats if b.optional])
    for i, b in enumerate(kept):
        if b.gate is None:
            continue
        j = find_index(kept, b.gate.advance_to)
        if j < 0:
            raise ValueError(f"{b.id}: gate target {b.gate.advance_to!r} is optional "
                             "and may be skipped")
        if j <= i:
            raise ValueError(f"{b.id}: gate must advance forward after skips")


# The Mixar intro script lives in ``script.py`` (split for size); imported
# last because it builds on everything above.
from .script import MIXAR_INTRO  # noqa: E402,F401

