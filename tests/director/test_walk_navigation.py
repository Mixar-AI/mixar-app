# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Cinema Mode is not a walking mode until the director asks for one.

The surface used to hold a camera nudge on W/A/S/D/Q/E for the whole
session, so the keys moved the shot camera at any moment and the mouse came
with them — a mode nobody opted into. Walking is now something N turns on and
off, and what it turns on is BLENDER'S OWN `view3d.walk`, so every habit,
speed preference and modifier a Blender user already has still applies.

The strip's hints follow the state, because a hint is a promise: at rest it
advertises only O and I; while walking it advertises walk's own keys.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

from mixar.modules.director.core import viewport

ROOT = Path(__file__).resolve().parents[2]
DIRECTOR = ROOT / "src/scripts/mixar/modules/director"
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"
KEYMAP = (DIRECTOR / "ui/keymap.py").read_text(encoding="utf-8")
PROPS = (DIRECTOR / "ui/properties/director_properties.py").read_text(encoding="utf-8")
SESSION = (DIRECTOR / "ui/operators/session_ops.py").read_text(encoding="utf-8")
TOP = (VIEW3D / "view3d_director_cinema_top.cc").read_text(encoding="utf-8")
STATE = (VIEW3D / "view3d_director_state.cc").read_text(encoding="utf-8")
HEADER = (VIEW3D / "view3d_director.hh").read_text(encoding="utf-8")
WALK = (VIEW3D / "view3d_director_walk.cc").read_text(encoding="utf-8")
CAMERA_OPS = (DIRECTOR / "ui/operators/camera_ops.py").read_text(encoding="utf-8")


def _hint_block(array: str) -> str:
    return TOP.split(f"const Hint {array}[", 1)[1].split("};", 1)[0]


# ---- the resting surface --------------------------------------------------


def test_at_rest_the_strip_advertises_only_o_and_i():
    block = _hint_block("resting_hints")
    assert '{"O"}' in block and '{"I"}' in block
    # And nothing else: no camera keys while none of them do anything, and
    # no walk key because there is none to promise.
    assert set(re.findall(r'"([A-Z])"', block)) == {"O", "I"}
    assert "RESTING_HINTS = 2" in TOP


def test_walking_advertises_the_walks_own_keys():
    block = _hint_block("walking_hints")
    assert '{"W", "A", "S", "D"}' in block
    assert '{"Q", "E"}' in block
    assert '{"LMB"}' in block and "Hold to look" in block
    # The sprint and the creep share one group, the way Q and E do.
    assert '{"Shift", WALK_SLOW_KEY}, 2, "Faster / slower"' in block
    assert "WALKING_HINTS = 4" in TOP


def test_no_key_is_promised_as_the_way_out():
    """No key stops the walk — the lit Walk chip beside the hints is the way
    out — so a keycap for one would be a promise the walk does not keep."""
    block = _hint_block("walking_hints")
    assert '"Esc"' not in block and "Done" not in block


def test_the_slow_key_is_named_as_the_keyboard_labels_it():
    """Alt is Option on a Mac keyboard, as the Sketch talk hint says too."""
    assert '#  define WALK_SLOW_KEY "Option"' in TOP
    assert '#  define WALK_SLOW_KEY "Alt"' in TOP
    assert TOP.index("#ifdef __APPLE__") < TOP.index('#  define WALK_SLOW_KEY "Option"')


def test_the_strip_chooses_its_set_from_the_live_state():
    assert "const Hint *source = state.walking ? walking_hints : resting_hints;" in TOP
    assert "const int hint_count = state.walking ? WALKING_HINTS : RESTING_HINTS;" in TOP


def test_a_word_keycap_widens_instead_of_spilling():
    """"Shift" and "Mouse" do not fit the square cap a single glyph gets."""
    paint = (VIEW3D / "view3d_director_cinema_paint.cc").read_text(encoding="utf-8")
    assert "float cinema_keycap_width(const char *label)" in paint
    assert "float cinema_keycap(const float x, const float y, const char *letter)" in paint
    assert "const float width = cinema_keycap_width(letter);" in paint
    # The packing asks for the real width rather than assuming the square.
    assert "cinema_keycap_width(hint.keys[key]) / u" in TOP
    assert "x += cinema_keycap(x, row_y, hint.keys[key]) + 2.0f * u;" in TOP


# ---- the state the strip reads --------------------------------------------


def test_walk_active_is_session_state_that_never_reaches_a_blend():
    block = PROPS.split("walk_active: BoolProperty(", 1)[1].split("\n    )", 1)[0]
    assert "default=False" in block
    assert "options={'SKIP_SAVE'}" in block
    assert "_redraw_director_surface" in block, "the strip has to repaint on it"


def test_the_native_side_reads_it():
    assert "bool walking = false;" in HEADER
    assert 'r_state->walking = director_bool(&state_ptr, "walk_active", false);' in STATE


def test_the_supervisor_sets_and_clears_it():
    published = []
    context = SimpleNamespace(
        scene=SimpleNamespace(mixar_director=SimpleNamespace(walk_active=False))
    )

    viewport.set_walk_active(context, True)
    published.append(context.scene.mixar_director.walk_active)
    viewport.set_walk_active(context, False)
    published.append(context.scene.mixar_director.walk_active)

    assert published == [True, False]
    # Both ends of the supervisor, including the cancel path through _finish.
    camera_ops = (DIRECTOR / "ui/operators/camera_ops.py").read_text(encoding="utf-8")
    assert "set_walk_active(context, True)" in camera_ops
    assert "set_walk_active(context, False)" in camera_ops


def test_publishing_survives_a_scene_without_the_state():
    viewport.set_walk_active(SimpleNamespace(scene=None), True)
    viewport.set_walk_active(SimpleNamespace(), True)  # must not raise


def test_entering_and_leaving_the_mode_clears_a_stranded_flag():
    """A supervisor that never reached its exit would otherwise leave the
    strip advertising walk's keys for the rest of the session."""
    assert SESSION.count("state.walk_active = False") >= 3


# ---- the keys -------------------------------------------------------------


def test_the_camera_keys_are_inert_until_a_walk_runs():
    assert "_WALK_KEYS = ('W', 'A', 'S', 'D', 'Q', 'E')" in KEYMAP
    assert "director_nudge_camera" not in KEYMAP
    block = KEYMAP[KEYMAP.index("for key in _WALK_KEYS:"):]
    block = block[: block.index("addon_keymaps.append")]
    assert '"mixar.director_block_input"' in block


def test_walking_has_no_keyboard_shortcut():
    """Both keys that fitted were already somebody else's.

    `N` is the sidebar. `Shift`+`` ` `` is what Blender binds `view3d.walk`
    to — and what Mixar's own moodboard keymap binds the Zen drawer to, which
    is what a real build showed. The chip is the entry point instead, and
    this pins that nothing quietly re-takes a key later.
    """
    assert "_WALK_KEY = " not in KEYMAP
    assert "_WALK_TOGGLE_KEYMAPS" not in KEYMAP
    assert "_register_walk_exit" not in KEYMAP
    assert "View3D Walk Modal" not in KEYMAP
    # N stays guarded chrome.
    assert "(\"3D View Generic\", ('VIEW_3D', 'WINDOW'), 'N', {})" in KEYMAP
    # And the key the moodboard owns is not bound here at all.
    assert "ACCENT_GRAVE" not in KEYMAP
    moodboard = (
        ROOT / "src/scripts/mixar/modules/moodboard/ui/keymap.py"
    ).read_text(encoding="utf-8")
    assert "ACCENT_GRAVE" in moodboard, "the collision this records is gone — recheck"


# ---- entering the mode ----------------------------------------------------


def test_cinema_mode_looks_through_the_last_active_camera():
    """Not a toggle: `view3d.view_camera` would flip a viewport that already
    was in camera view back out of it."""
    enter = SESSION.split("class MIXAR_OT_director_enter", 1)[1]
    enter = enter.split("class ", 1)[0]
    assert "enter_camera_view(context, camera)" in enter
    assert "bpy.ops.view3d.view_camera" not in SESSION
    assert "_existing_camera(context, active_shot(context.scene))" in enter


def test_entering_the_mode_never_creates_a_camera():
    helper = SESSION.split("def _existing_camera(", 1)[1].split("\ndef ", 1)[0]
    assert "create_camera_from_view" not in helper
    assert "return camera if camera is not None and camera.type == 'CAMERA' else None" in helper


def test_cinema_mode_adopts_the_camera_it_opens_on():
    """Looking through a camera without adopting it left the session with no
    active shot, and every shot-gated control reads that as "nothing to do":
    the Walk chip came up greyed out and the My Cameras row never lit, on a
    surface plainly looking through that very camera."""
    enter = SESSION.split("class MIXAR_OT_director_enter", 1)[1].split("\nclass ", 1)[0]
    assert "adopt_camera(context.scene, camera)" in enter
    assert "select_camera_object(context, camera)" in enter
    # Directing has to be live first: `_on_active_shot_change` only enters the
    # camera view and selects while `is_directing`.
    assert enter.index("state.is_directing = True") < enter.index("adopt_camera(")


def test_the_walk_chip_is_gated_on_an_editable_shot():
    """Which is exactly why entering has to adopt one."""
    camera_ops = (DIRECTOR / "ui/operators/camera_ops.py").read_text(encoding="utf-8")
    navigate = camera_ops.split("class MIXAR_OT_director_navigate", 1)[1]
    navigate = navigate.split("\n    def invoke(", 1)[0]
    assert "state.is_directing and _editable_shot(context)" in navigate
    # The chip carries no disable of its own — Blender greys it out from the
    # poll, so the poll is the whole contract.
    chip = TOP.split("void walk_chip(", 1)[1].split("\n}\n", 1)[0]
    assert "director_overlay_disable_button" not in chip


# ---- the chip in the strip ------------------------------------------------


def test_the_strip_carries_a_walk_chip():
    """A keyboard-only entry point is not one a director discovers."""
    chip = TOP.split("void walk_chip(", 1)[1].split("\n}\n", 1)[0]
    assert '"MIXAR_OT_director_navigate"' in chip
    # A camera: the chip drives the shot camera. Not the pan hand (the
    # viewport's own Move) and not the stick figure (an armature).
    assert "ICON_VIEW_CAMERA," in chip
    assert "ICON_VIEW_PAN" not in chip and "ICON_ARMATURE_DATA" not in chip
    assert 'cinema_qa_record(region, chip, "director_walk"' in chip
    # Lit while a walk is running, like the grid chip's on state.
    assert "MIXAR_THEME_LOAD(on, Primary);" in chip
    # And while lit it offers the way OUT. The chip always looked like a
    # toggle — lit, publishing "stop" — and was not one; a second click
    # started a second walk once the surface became clickable during one.
    assert "Stop walking" in chip
    # ... and it is the ONLY way out, so it no longer points at others.
    assert "Esc" not in chip.split("cinema_icon_button(", 1)[1]
    assert "right-click" not in chip
    assert 'cinema_qa_record(region, chip, "director_walk", walking ? "stop" : "start", -1);' in chip


def test_the_chip_sits_left_of_the_grid_chip_and_the_hints_yield_to_it():
    assert "rctf walk = {grid.xmin - (CINEMA_STRIP_GAP + CINEMA_PHONE_H) * u," in TOP
    assert "const float controls_left = walk.xmin;" in TOP
    assert "walk_chip(block, region, walk, state.walking);" in TOP


# ---- walking is where the mode starts ------------------------------------


def test_cinema_mode_starts_walking():
    """Cinema Mode is camera work, so the director should already be flying
    when the surface appears rather than reaching for the chip first."""
    enter = SESSION.split("class MIXAR_OT_director_enter", 1)[1].split("\nclass ", 1)[0]
    assert "_start_walking(self, context)" in enter
    # Last: the walk's poll needs the shot the adoption above creates, on a
    # camera that is already selected and looked through.
    assert enter.index("adopt_camera(") < enter.index("_start_walking(")

    helper = SESSION.split("def _start_walking(", 1)[1].split("\ndef ", 1)[0]
    assert "bpy.ops.mixar.director_navigate('INVOKE_DEFAULT')" in helper
    # Best effort: no camera, a locked take or a viewport that refuses the
    # modal all leave the mode open and simply not walking.
    assert "except Exception" in helper
    assert 'operator.report({\'INFO\'}' in helper
    # And it never stacks a second walk on a running one.
    assert 'getattr(context.scene.mixar_director, "walk_active", False)' in helper


def test_the_chip_can_actually_stop_the_walk():
    """Python cannot cancel a modal, so the second click asks through a flag
    the native walk clears on the tick it stops."""
    navigate = CAMERA_OPS.split("class MIXAR_OT_director_navigate", 1)[1]
    assert "if _walk_running_in(context.window):" in navigate
    assert "state.walk_stop_requested = True" in navigate
    assert navigate.index("walk_stop_requested") < navigate.index("invoke_walk(")

    stop = WALK.split("bool director_walk_stop_requested(", 1)[1].split("\n}\n", 1)[0]
    assert '"walk_stop_requested"' in stop
    # Cleared where it is read, so a request cannot outlive the walk it ended.
    assert "RNA_property_boolean_set(&state_ptr, prop, false);" in stop
    tick = WALK.split("wmOperatorStatus director_walk_tick(", 1)[1].split("\n}\n", 1)[0]
    assert "if (director_walk_stop_requested(C)) {" in tick
    assert "return director_walk_finish(C, op);" in tick
