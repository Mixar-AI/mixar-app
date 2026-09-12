# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Source-level contracts of the C++ Parallel Agents panel.

The panel is custom-drawn native code with no Python surface to exercise under
the ``bpy`` mock, so what can be checked here is the set of invariants whose
violation is silent at runtime:

* a fixed C++ buffer that is not strictly larger than the Python ``maxlen`` it
  mirrors is an off-by-one on every read (``StringProperty(maxlen=N)``
  registers maxlength ``N + 1``);
* geometry re-derived outside the layout pass goes stale against scroll and
  the slide-in, so clicks land on the wrong card;
* a custom-drawn surface with no QA target provider cannot be driven by the
  harness, which is what makes it unshippable;
* resizing the region from inside its own draw callback re-enters region init
  for the region on the stack.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPACE_VIEW3D = ROOT / "src" / "source" / "blender" / "editors" / "space_view3d"
PY_CONSTANTS = (
    ROOT / "src" / "scripts" / "mixar" / "modules" / "agent_panel" / "constants.py"
)
PY_PROPS = (
    ROOT
    / "src"
    / "scripts"
    / "mixar"
    / "modules"
    / "agent_panel"
    / "ui"
    / "properties"
    / "agent_card_props.py"
)

HEADER = SPACE_VIEW3D / "view3d_agent_panel.hh"
CARDS = SPACE_VIEW3D / "view3d_agent_panel_cards.cc"
SYNC = SPACE_VIEW3D / "view3d_agent_panel_sync.cc"
DRAW = SPACE_VIEW3D / "view3d_agent_panel_draw.cc"
OPS = SPACE_VIEW3D / "view3d_agent_panel_ops.cc"
QA = SPACE_VIEW3D / "view3d_agent_panel_qa.cc"
SPACE = SPACE_VIEW3D / "space_view3d.cc"
CMAKE = SPACE_VIEW3D / "CMakeLists.txt"


def _defines_float(text):
    values = {
        m.group(1): float(m.group(2))
        for m in re.finditer(r"^#define\s+(AGENT_PANEL_\w+)\s+([\d.]+)", text, re.M)
    }
    motion = (SPACE_VIEW3D.parent / "include/UI_mixar_motion.hh").read_text()
    tokens = {
        m.group(1): float(eval(m.group(2), {"__builtins__": {}}, {}))
        for m in re.finditer(r"constexpr double (\w+) = ([\d. /]+);", motion)
    }
    for name, token in re.findall(r"#define (AGENT_PANEL_\w+) ui::mixar_motion::(\w+)", text):
        values[name] = tokens[token]
    return values


def _defines(text):
    return {
        m.group(1): int(m.group(2))
        for m in re.finditer(r"^#define\s+(AGENT_PANEL_\w+)\s+(\d+)", text, re.M)
    }


class TestStringBudgets:
    """Every C++ buffer is strictly larger than the maxlen it mirrors."""

    def test_buffers_exceed_their_python_maxlens(self):
        defines = _defines(HEADER.read_text())
        py = PY_CONSTANTS.read_text()
        maxlens = {
            m.group(1): int(m.group(2))
            for m in re.finditer(r"^(\w+_MAXLEN)\s*=\s*(\d+)", py, re.M)
        }
        pairs = (
            ("AGENT_PANEL_TASK_ID_BUF", "AGENT_TASK_ID_MAXLEN"),
            ("AGENT_PANEL_NAME_BUF", "AGENT_NAME_MAXLEN"),
            ("AGENT_PANEL_TASK_BUF", "AGENT_TASK_MAXLEN"),
        )
        for buf_name, maxlen_name in pairs:
            assert buf_name in defines, f"{buf_name} missing from the header"
            assert maxlen_name in maxlens, f"{maxlen_name} missing from constants.py"
            assert defines[buf_name] > maxlens[maxlen_name], (
                f"{buf_name} ({defines[buf_name]}) must exceed {maxlen_name} "
                f"({maxlens[maxlen_name]}): StringProperty(maxlen=N) stores N "
                "characters plus the NUL"
            )

    def test_the_properties_declare_those_maxlens(self):
        props = PY_PROPS.read_text()
        for name in ("AGENT_TASK_ID_MAXLEN", "AGENT_NAME_MAXLEN", "AGENT_TASK_MAXLEN"):
            assert f"maxlen={name}" in props, (
                f"{name} must be the declared maxlen, not a repeated literal"
            )

    def test_every_string_read_is_bounded(self):
        """`RNA_property_string_get` is strcpy-shaped — never call it raw."""
        text = SYNC.read_text()
        assert "agent_panel_read_string" in text
        assert not re.search(r"\bRNA_property_string_get\s*\(", text), (
            "read through agent_panel_read_string, which uses the _alloc form"
        )


class TestOneLayoutOwner:
    """Draw, hit test and QA targets read the rects; only layout writes them."""

    def test_only_the_layout_pass_assigns_card_rects(self):
        for path in (DRAW, OPS, QA):
            text = path.read_text()
            assert not re.search(r"\.rect\.(xmin|xmax|ymin|ymax)\s*=", text), (
                f"{path.name} writes a card rect — geometry has one owner, "
                "view3d_agent_panel_layout_cards"
            )

    def test_the_scroll_offset_is_applied_in_the_layout_pass(self):
        text = CARDS.read_text()
        layout = text[text.index("void view3d_agent_panel_layout_cards") :]
        assert "runtime->scroll" in layout, (
            "scroll must move the rects themselves, or draw and hit-test disagree"
        )

    def test_the_reveal_animation_is_applied_in_the_layout_pass(self):
        text = CARDS.read_text()
        layout = text[text.index("void view3d_agent_panel_layout_cards") :]
        assert "card.slide.sample" in layout, (
            "a card animating in must be clickable where it is drawn"
        )

    def test_scrolling_only_moves_the_scroll_position(self):
        text = OPS.read_text()
        assert "runtime->scroll =" in text
        assert "layout_cards" not in text, (
            "the operator must not lay out — the next draw does, and re-clamps"
        )


class TestColumnClip:
    """`region->winy` is the whole area height on a right dock, so "visible"
    has to mean the card column, not the region."""

    def test_the_layout_pass_defines_the_column(self):
        text = CARDS.read_text()
        layout = text[text.index("void view3d_agent_panel_layout_cards") :]
        assert "runtime->column_rect" in layout

    def test_the_chevron_exists_only_when_there_is_more_to_see(self):
        """It is the discoverable half of scrolling. Keyed on the card count,
        not on `scroll_max` alone: a short viewport squeezes the column and
        gives a non-zero `scroll_max` at three cards or fewer, and a chevron
        beside a stack that plainly shows everything reads as a bug. Both
        conditions hold, so it is also never a dead control."""
        text = CARDS.read_text()
        layout = text[text.index("void view3d_agent_panel_layout_cards") :]
        assert "n > AGENT_PANEL_VISIBLE_CARDS && runtime->scroll_max > 0.0f" in layout
        assert "runtime->chevron_rect" in layout

    def test_the_hit_extent_covers_the_cards_and_the_chevron(self):
        """For an overlapping side region `ED_region_contains_xy` tests the
        event against `v2d.tot` and bails when `v2d.mask` is degenerate — a
        custom-drawn region that never sets up a View2D is transparent to
        every event, with the keymap resolving and nothing arriving."""
        text = CARDS.read_text()
        assert "agent_panel_view2d_sync" in text
        sync = text[text.index("static void agent_panel_view2d_sync") :]
        assert "v2d->mask" in sync and "v2d->tot" in sync
        layout = text[text.index("void view3d_agent_panel_layout_cards") :]
        assert "BLI_rcti_union(&hit, &runtime->chevron_rect)" in layout

    def test_draw_hit_test_and_qa_share_one_visibility_test(self):
        for path in (DRAW, QA):
            assert "view3d_agent_panel_card_visible(" in path.read_text(), (
                f"{path.name} must ask the shared test, not re-derive bounds"
            )
        assert "runtime->column_rect" in CARDS.read_text()

    def test_nothing_culls_against_the_region_height(self):
        for path in (DRAW, QA):
            text = path.read_text()
            assert "region->winy" not in text, (
                f"{path.name} culls against the region — a five-card fan-out "
                "would then paint every card and scrolling would do nothing"
            )

    def test_the_draw_pass_scissors_and_restores(self):
        text = DRAW.read_text()
        assert "GPU_scissor_get" in text and "GPU_scissor(" in text, (
            "a half-scrolled card must clip at the column edge"
        )
        assert text.count("GPU_scissor(") >= 2, "the previous scissor must be restored"


class TestRevealReplaysEveryTurn:
    def test_the_restart_is_keyed_on_pythons_generation_counter(self):
        """`cards_sync` runs only from draw, and draw does not run while the
        panel is poll-hidden — so between turns the card vector still holds
        the previous turn's cards. Neither an emptiness test nor a task-id
        comparison can see a new fan-out from here: the first animates once
        per session, the second leaves a re-run of the same turn's task list
        stuck at the previous scroll position."""
        text = SYNC.read_text()
        sync = text[text.index("void view3d_agent_panel_cards_sync") :]
        assert "mixar_agent_cards_generation" in sync
        assert "runtime->scroll = 0.0f" in sync and "reveal_started_at" in sync
        assert "was_empty" not in sync

    def test_python_bumps_the_generation_for_every_new_fan_out(self):
        cards_py = (
            ROOT
            / "src"
            / "scripts"
            / "mixar"
            / "modules"
            / "agent_panel"
            / "core"
            / "cards.py"
        ).read_text()
        assert "_bump_generation" in cards_py
        clear = cards_py[cards_py.index("def clear_cards") :]
        clear = clear[: clear.index("\ndef ")]
        assert "_bump_generation" in clear


class TestPollDrivenVisibility:
    def test_a_space_listener_turns_notifiers_into_a_refresh(self):
        """Region polls re-run only on a screen refresh, which a redraw tag is
        not — without this the panel does not appear when a turn fans out
        until some unrelated edit happens to refresh the screen."""
        text = CARDS.read_text()
        assert "view3d_agent_panel_space_listener" in text
        listener = text[text.index("void view3d_agent_panel_space_listener") :]
        listener = listener[: listener.index("\nstatic ")]
        assert "ED_area_tag_refresh" in listener
        assert "ED_area_tag_redraw_regiontype" in listener, (
            "a region the refresh brings back has no regiondata until it draws"
        )
        assert "view3d_agent_panel_space_listener(params);" in SPACE.read_text()

    def test_region_init_tags_its_own_first_redraw(self):
        draw = DRAW.read_text()
        init = draw[draw.index("void view3d_agent_panel_region_init") :]
        init = init[: init.index("\nvoid ")]
        assert "ED_region_tag_redraw(region)" in init


class TestTickTimer:
    def test_the_timer_stops_once_the_panel_settles(self):
        """Cards persist after a turn ends; an ungated timer would keep
        ticking over the viewport until the next one."""
        text = DRAW.read_text()
        draw_fn = text[text.index("void view3d_agent_panel_region_draw") :]
        assert "view3d_agent_panel_tick_timer_ensure(C, runtime);" in draw_fn
        assert "view3d_agent_panel_tick_timer_remove(CTX_wm_manager(C), runtime);" in draw_fn
        assert "view3d_agent_panel_is_animating(runtime)" in draw_fn


class TestAnimationFrameRate:
    """The tick interval IS the animation's frame rate, so both halves of that
    have to hold: the tick has to be fast, and it has to be the thing that
    asks for the repaint."""

    def test_the_repaint_is_requested_from_a_listener_not_from_the_draw(self):
        """`wm_draw.cc` sets `region->runtime->do_draw = 0` immediately AFTER
        `ED_region_do_draw` returns, so a redraw tagged from inside the draw
        callback is wiped before it can take effect — the panel then animates
        at whatever else happens to repaint it."""
        cards = CARDS.read_text()
        assert "agent_panel_region_listener" in cards
        listener = cards[cards.index("static void agent_panel_region_listener") :]
        listener = listener[: listener.index("\nstatic ")]
        assert "ED_region_tag_redraw(region)" in listener
        assert "view3d_agent_panel_is_animating(runtime)" in listener, (
            "a settled panel must not repaint on every notifier"
        )
        assert "art->listener = agent_panel_region_listener;" in cards

        draw_fn = DRAW.read_text()
        draw_fn = draw_fn[draw_fn.index("void view3d_agent_panel_region_draw") :]
        assert "ED_region_tag_redraw(region)" not in draw_fn, (
            "tagging from the draw pass is dead code and hides the real driver"
        )

    def test_the_tick_runs_at_display_cadence(self):
        assert _defines_float(HEADER.read_text())["AGENT_PANEL_TICK_INTERVAL"] <= 1.0 / 50.0, (
            "the tick interval is the animation's frame rate, not a poll rate"
        )


class TestFinishedCardsLeave:
    """A completed agent has nothing left to say; its card slides out."""

    def test_the_two_halves_of_the_exit_agree_on_timing(self):
        """Python owns WHEN the card leaves the mirror, C++ owns the slide,
        timed from its own first sighting of DONE. The clocks share no epoch,
        so they are never compared — only given matching durations. If the C++
        half outlasts the Python half the card vanishes mid-slide."""
        defines = _defines_float(HEADER.read_text())
        py = PY_CONSTANTS.read_text()
        consts = {
            m.group(1): float(m.group(2))
            for m in re.finditer(r"^(DONE_CARD_\w+)\s*=\s*([\d.]+)", py, re.M)
        }
        assert defines["AGENT_PANEL_DONE_DWELL_SECONDS"] == consts["DONE_CARD_DWELL_S"]
        assert defines["AGENT_PANEL_EXIT_SECONDS"] == consts["DONE_CARD_EXIT_S"]

    def test_only_done_cards_leave(self):
        """A failure is the one thing on this surface the user may still need
        to act on, so it stays until dismissed."""
        text = CARDS.read_text()
        fn = text[text.index("float view3d_agent_panel_exit_progress") :]
        fn = fn[: fn.index("\nfloat ")]
        assert "AgentCardStatus::Done" in fn
        assert "return 0.0f;" in fn

    def test_the_exit_keeps_the_panel_redrawing(self):
        text = CARDS.read_text()
        fn = text[text.index("bool view3d_agent_panel_is_animating") :]
        fn = fn[: fn.index("\n/** \\} */")]
        assert "view3d_agent_panel_exit_progress" in fn, (
            "the slide is time-driven; without this it freezes part-way"
        )

    def test_a_dismissal_animates_before_the_row_goes(self):
        """Removing on the click makes the card vanish from under the cursor.
        The click marks; the panel plays the same slide-out; the row goes
        after it."""
        cards_py = (
            ROOT / "src" / "scripts" / "mixar" / "modules" / "agent_panel"
            / "core" / "cards.py"
        ).read_text()
        fn = cards_py[cards_py.index("def begin_dismiss") :]
        fn = fn[: fn.index("\ndef ")]
        assert "card.dismissing = True" in fn
        assert "_schedule_exit(task_id, dwell=0.0)" in fn, (
            "a dismissal is a direct answer to a click and leaves at once"
        )
        assert "dismiss_card" not in fn, "the row must not go on the click"

        ops_py = (
            ROOT / "src" / "scripts" / "mixar" / "modules" / "agent_panel"
            / "ui" / "operators" / "agent_panel_ops.py"
        ).read_text()
        assert "begin_dismiss" in ops_py

        text = CARDS.read_text()
        fn = text[text.index("float view3d_agent_panel_exit_progress") :]
        fn = fn[: fn.index("\nfloat ")]
        assert "card.dismissing" in fn

    def test_arrivals_share_zen_timing_with_a_bounded_stagger(self):
        """Offscreen tasks must not extend how long the visible fan-out settles."""
        defines = _defines_float(HEADER.read_text())
        assert defines["AGENT_PANEL_REVEAL_SECONDS"] == 0.26
        assert defines["AGENT_PANEL_STAGGER_SECONDS"] == 0.05
        assert "std::min(arrivals++, AGENT_PANEL_VISIBLE_CARDS - 1)" in SYNC.read_text()

    def test_python_schedules_the_removal_and_rechecks_on_fire(self):
        cards_py = (
            ROOT / "src" / "scripts" / "mixar" / "modules" / "agent_panel"
            / "core" / "cards.py"
        ).read_text()
        fn = cards_py[cards_py.index("def _schedule_exit") :]
        fn = fn[: fn.index("\ndef ")]
        assert "bpy.app.timers.register" in fn
        assert "dwell + DONE_CARD_EXIT_S" in fn
        assert "card.dismissing or card.status == 'DONE'" in fn, (
            "a task that goes DONE and is then re-run keeps its card"
        )


class TestTrackpadScrolls:
    def test_the_scroll_binds_trackpad_pan_as_well_as_the_wheel(self):
        """A trackpad two-finger scroll arrives as MOUSEPAN, never as a wheel
        event — with only the wheel bound the panel is unscrollable on a
        laptop and the gesture falls through to the viewport."""
        ops = OPS.read_text()
        assert "pan_params.type = MOUSEPAN;" in ops
        assert "event->type != MOUSEPAN" in ops
        assert "WM_event_absolute_delta_y" in ops, (
            "that helper already accounts for the natural-scrolling preference"
        )
        keymap = (
            ROOT / "src" / "scripts" / "mixar" / "modules" / "agent_panel"
            / "ui" / "keymap.py"
        ).read_text()
        assert "TRACKPADPAN" in keymap, (
            "the addon keyconfig is the copy that survives a preset reload"
        )


class TestDrawSafety:
    def test_the_draw_pass_never_resizes_the_region(self):
        """A draw pass has the framebuffer bound and is iterating
        `area->regionbase` (the Agent Bubble footer crash class)."""
        text = DRAW.read_text()
        for banned in ("ED_screen_refresh", "Mixar_WindowForceSize", "ED_area_tag_refresh"):
            assert banned not in text, f"{banned} must not run from the panel draw"

    def test_the_panel_is_transparent_when_regions_overlap(self):
        text = DRAW.read_text()
        assert "region->overlap" in text and "GPU_clear_color" in text, (
            "the cards float over the viewport; an opaque clear would black it out"
        )


class TestWiring:
    def test_the_region_docks_bottom_not_left(self):
        """The card stack sits bottom-left, but the REGION is bottom-aligned.

        Blender stacks overlapping regions that share an edge instead of
        letting them overlap each other, so a left-docked panel pushes the
        tool shelf bodily out into the viewport.
        """
        text = SPACE.read_text()
        block = text[text.index("parallel agents panel (Mixar)") :][:900]
        assert "RGN_ALIGN_BOTTOM" in block
        assert "RGN_ALIGN_LEFT" not in block
        assert "RGN_TYPE_EXECUTE" in block

    def test_saved_files_are_migrated_off_the_old_strip_size(self):
        versioning = (
            ROOT
            / "src"
            / "source"
            / "blender"
            / "blenloader"
            / "intern"
            / "versioning_mixar_200.cc"
        ).read_text()
        block = versioning[versioning.index("MAIN_MIXAR_VERSION_FILE_ATLEAST(bmain, 100, 4)") :]
        block = block[:1400]
        assert "RGN_ALIGN_BOTTOM" in block
        assert "region->sizey = 0" in block, (
            "the stored size came from the tile strip and must be re-taken "
            "from the region type"
        )

    def test_the_region_type_declares_a_height_not_a_width(self):
        text = CARDS.read_text()
        assert "art->prefsizey = AGENT_PANEL_PREFSIZEY;" in text
        assert "art->prefsizex" not in text, "a bottom dock is sized by height"

    def test_the_qa_target_provider_is_registered(self):
        assert "Mixar_qa_register_target_provider" in QA.read_text()
        assert "view3d_agent_panel_qa_targets_register();" in SPACE.read_text()

    def test_qa_targets_read_the_stored_rects(self):
        text = QA.read_text()
        assert "runtime->cards" in text
        assert "view3d_agent_panel_runtime_ensure(" not in text, (
            "a target dump must never allocate region data"
        )

    def test_every_source_file_is_built(self):
        cmake = CMAKE.read_text()
        for path in (CARDS, SYNC, DRAW, OPS, QA):
            assert path.name in cmake, f"{path.name} missing from CMakeLists.txt"
        assert HEADER.name in cmake

    def test_the_retired_scene_strip_is_gone(self):
        """Its tiles previewed per-agent scenes, which parallel tasks no
        longer get. Leaving the old surface registered would fight this one
        for the same RGN_TYPE_EXECUTE region."""
        assert not list(SPACE_VIEW3D.glob("view3d_agent_strip*"))
        assert "agent_strip" not in SPACE.read_text()
        assert "agent_strip" not in CMAKE.read_text()


class TestKeymapSurvivesPresetReload:
    def test_the_bindings_exist_in_the_addon_keyconfig(self):
        """A GUI keyconfig preset reload empties C-registered default-config
        keymaps, so the addon copy is the one that actually resolves."""
        keymap = (
            ROOT
            / "src"
            / "scripts"
            / "mixar"
            / "modules"
            / "agent_panel"
            / "ui"
            / "keymap.py"
        ).read_text()
        assert "'Agent Panel'" in keymap
        assert "view3d.agent_panel_scroll" in keymap

    def test_the_addon_keymap_name_matches_the_c_side(self):
        for path in (DRAW, OPS):
            assert '"Agent Panel"' in path.read_text(), (
                f"{path.name} must ensure the same keymap identity"
            )
