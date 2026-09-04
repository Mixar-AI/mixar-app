# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Source-level contracts for the parts of Scribble Marks that need Blender.

``bpy`` is a MagicMock in this suite, so an operator's ``execute`` cannot be
exercised — a mock accepts every call and returns another mock, which would
make these tests pass no matter what the code did. The repo's answer, used by
the moodboard and job-queue suites, is to pin the contract at the source
level instead. That is what this file does, and it is aimed at the mistakes
that are silent in Blender:

* a positional argument added to one of four call sites and not the others;
* a draw callback that writes scene state;
* session state accidentally saved into the .blend, or scene state that isn't.
"""

import ast
import pathlib

import pytest


REPO = pathlib.Path(__file__).resolve().parents[2]
SRC = REPO / "src/scripts/mixar/modules"
MODULE = SRC / "scribble_mark"


def source(path):
    return (REPO / path).read_text()


def tree(path):
    return ast.parse(source(path))


# =============================================================================
# The SSE positional chain
# =============================================================================

SSE = "src/scripts/mixar/modules/space_mixie_chat/core/sse_handler.py"


class TestStreamArgumentChain:
    """``_stream_loop`` is called in two places — the thread start and its own
    reconnect recursion — both POSITIONALLY. Adding a parameter to the
    signature and one call site but not the other shifts every later argument
    by one, which type-checks fine and silently sends the user's preferences
    as the mark payload."""

    def _func(self, name):
        for node in ast.walk(tree(SSE)):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
        raise AssertionError(f"{name} not found in {SSE}")

    def _params(self, name):
        func = self._func(name)
        return [a.arg for a in func.args.args if a.arg != "self"]

    def test_stream_loop_declares_mark_context(self):
        assert "mark_context" in self._params("_stream_loop")

    def test_start_stream_declares_mark_context(self):
        assert "mark_context" in self._params("start_stream")

    def test_every_positional_call_matches_the_signature_order(self):
        params = self._params("_stream_loop")
        text = source(SSE)

        calls = []
        for node in ast.walk(tree(SSE)):
            if not isinstance(node, ast.Call):
                continue

            # The thread hand-off, matched on its TARGET rather than on the
            # presence of an args= tuple: the input stream is a sibling
            # Thread(...) call with its own signature, and it must not be
            # held to this one's.
            keywords = {kw.arg: kw.value for kw in node.keywords}
            target = keywords.get("target")
            targets_stream_loop = (
                isinstance(target, ast.Attribute) and target.attr == "_stream_loop"
            )
            if targets_stream_loop and isinstance(keywords.get("args"), ast.Tuple):
                calls.append([
                    e.id for e in keywords["args"].elts if isinstance(e, ast.Name)
                ])

            # The reconnect recursion: self._stream_loop(a, b, c, ...)
            if (isinstance(node.func, ast.Attribute)
                    and node.func.attr == "_stream_loop"):
                calls.append([
                    a.id for a in node.args if isinstance(a, ast.Name)
                ])

        assert calls, "no positional call to _stream_loop found — did it move?"
        for names in calls:
            # Every name passed must appear in the signature, in the same
            # relative order. A dropped or reordered argument fails here.
            positions = [params.index(n) for n in names if n in params]
            assert positions == sorted(positions), (
                f"positional arguments out of order against the signature: {names}"
            )
            assert "mark_context" in names, (
                f"a _stream_loop call site does not forward mark_context: {names}"
            )
        assert "mark_context" in text


# =============================================================================
# The send path
# =============================================================================

CHAT_OPS = "src/scripts/mixar/modules/space_mixie_chat/ui/operators/chat_ops.py"


class TestSendPath:
    def test_marks_are_prepared_before_attachments_are_encoded(self):
        """prepare_for_send appends the frozen frames to pending_attachments.
        Running it after the encoding pass would send the marks with no
        picture of them."""
        text = source(CHAT_OPS)
        prepare = text.index("chat_bridge.prepare_for_send")
        encode = text.index("image_encoding_total")
        assert prepare < encode

    def test_nothing_can_cancel_the_send_after_the_frames_are_attached(self):
        """The window between attaching and sending must be empty of
        bail-outs. A pre-flight check cancelling after prepare_for_send leaves
        the frozen frames queued for the NEXT message, carrying marks that
        were never settled — and the user sees them appear on a message they
        did not mark."""
        import re

        text = source(CHAT_OPS)
        prepare = text.index("chat_bridge.prepare_for_send")
        send = text.index("sse_handler.start_stream")

        for match in re.finditer(r"return \{'CANCELLED'\}", text):
            if not (prepare < match.start() < send):
                continue
            # The one legal exception: the modify / awaiting-input branch,
            # which prepare_for_send never runs for.
            preceding = text[prepare:match.start()]
            assert "if is_modify or is_awaiting_input:" in preceding, (
                "a cancelling return sits between attaching the frozen frames "
                "and sending them"
            )

    def test_the_websocket_preflight_runs_before_the_frames_are_attached(self):
        """The commonest cancel of all — no connection — must land before
        anything is queued."""
        text = source(CHAT_OPS)
        assert text.index("WebSocket not ready") < text.index(
            "chat_bridge.prepare_for_send"
        )

    def test_mark_context_reaches_start_stream(self):
        assert "mark_context=mark_context" in source(CHAT_OPS)

    def test_marks_are_settled_after_the_send(self):
        text = source(CHAT_OPS)
        assert "chat_bridge.finish_send" in text
        assert text.index("start_stream") < text.index("chat_bridge.finish_send")

    def test_the_marks_never_break_a_send(self):
        """The words are a complete request on their own. Every mark call in
        the send path is wrapped."""
        node = None
        for candidate in ast.walk(tree(CHAT_OPS)):
            if isinstance(candidate, ast.FunctionDef) and candidate.name == "execute":
                node = candidate
                break
        assert node is not None

        guarded = []
        for handler in ast.walk(node):
            if isinstance(handler, ast.Try):
                body = ast.dump(ast.Module(body=handler.body, type_ignores=[]))
                if "chat_bridge" in body:
                    guarded.append(handler)
        assert len(guarded) >= 2, "mark calls in the send path must be wrapped"


# =============================================================================
# Property lifetimes
# =============================================================================

PROPS = "src/scripts/mixar/modules/scribble_mark/ui/properties/mark_props.py"


class TestPropertyLifetimes:
    def test_marks_are_saved_with_the_file(self):
        """A mark is a scene noun the agent addresses turns later, and the
        vertex groups and cameras it names are saved beside it."""
        text = source(PROPS)
        for name in ("mixar_marks", "mixar_mark_serial", "mixar_mark_frame_name"):
            assert f"bpy.types.Scene.{name}" in text

    def test_the_armed_flag_is_session_only_and_never_saved(self):
        """A .blend reopened mid-freeze — viewport blocked, no modal left to
        unblock it — would be a file the user could not navigate."""
        text = source(PROPS)
        assert "bpy.types.WindowManager.mixar_mark_armed" in text
        armed = text.index("mixar_mark_armed")
        following = text[armed:armed + 800]
        assert "SKIP_SAVE" in following

    def test_every_registered_property_is_unregistered(self):
        text = source(PROPS)
        registered = set()
        for line in text.splitlines():
            for owner in ("bpy.types.Scene.", "bpy.types.WindowManager."):
                if line.strip().startswith(owner):
                    registered.add(line.strip()[len(owner):].split()[0].split("=")[0].strip())
        unreg = text.split("def unregister")[1]
        for name in registered:
            assert name in unreg, f"{name} is registered but never unregistered"


# =============================================================================
# Draw-callback discipline
# =============================================================================

OVERLAY = "src/scripts/mixar/modules/scribble_mark/core/overlay.py"


class TestDrawCallback:
    def test_the_draw_pass_writes_no_scene_state(self):
        """Draw callbacks run on every mouse move. The repo's rule is
        absolute: handlers read, timers and operators write."""
        node = None
        for candidate in ast.walk(tree(OVERLAY)):
            if isinstance(candidate, ast.FunctionDef) and candidate.name == "_draw_callback":
                node = candidate
        assert node is not None

        for assignment in ast.walk(node):
            if isinstance(assignment, ast.Assign):
                for target in assignment.targets:
                    assert not isinstance(target, ast.Attribute), (
                        "the draw pass assigns to an attribute — scene writes "
                        "belong in the operator, not the handler"
                    )

    def test_the_draw_pass_cannot_raise(self):
        """A raising draw handler takes the viewport with it."""
        for node in ast.walk(tree(OVERLAY)):
            if isinstance(node, ast.FunctionDef) and node.name == "_draw_callback":
                assert any(isinstance(n, ast.Try) for n in node.body)
                return
        raise AssertionError("_draw_callback not found")

    def test_blend_state_is_restored_even_on_failure(self):
        """Leaving ALPHA blending on bleeds into every later viewport draw."""
        text = source(OVERLAY)
        assert "finally:" in text
        assert text.count("blend_set('NONE')") >= 1


# =============================================================================
# Freeze discipline
# =============================================================================

class TestFreezeDiscipline:
    def test_arming_refuses_without_a_captured_frame(self):
        """With nothing frozen the user would be drawing on a live viewport
        that can move under them, and every mark would describe a view that
        no longer exists."""
        text = source("src/scripts/mixar/modules/scribble_mark/ui/operators/mark_draw_ops.py")
        marker = text.index("self._session.take(")
        following = text[marker:marker + 600]
        assert "CANCELLED" in following

    def test_render_settings_are_restored(self):
        text = source("src/scripts/mixar/modules/scribble_mark/core/freeze.py")
        assert "finally:" in text
        for setting in ("resolution_x", "resolution_y", "file_format",
                        "resolution_percentage", "filepath"):
            assert text.count(setting) >= 2, f"{setting} saved but not restored"

    @pytest.mark.parametrize("module", ["freeze", "annotate"])
    def test_frames_are_packed_through_the_shared_loader(self, module):
        """Both frames live in bpy.app.tempdir, which is cleaned on exit, and
        a mark referencing a vanished image loses the one thing a VLM can
        read. `load_image_from_file` already packs and clears the temp path;
        a second copy of those steps is a second place for them to drift."""
        text = source(f"src/scripts/mixar/modules/scribble_mark/core/{module}.py")
        assert "load_image_from_file" in text
        assert ".pack()" not in text, "packing is the shared loader's job"

    def test_the_shared_loader_still_packs_and_clears_the_temp_path(self):
        """Pinned here because the freeze relies on it: if that helper ever
        stops clearing filepath_raw, a reload after tempdir cleanup reports a
        missing file for an image that is fully present."""
        text = source("src/scripts/mixar/modules/common/utils/image_utils.py")
        loader = text[text.index("def load_image_from_file"):]
        loader = loader[:loader.index("\ndef ", 1)] if "\ndef " in loader[1:] else loader
        assert ".pack()" in loader
        assert "filepath_raw" in loader

    def test_a_file_load_cannot_leave_the_viewport_frozen(self):
        """The modal dies on load but the overlay handler and the running
        guard are module state that survives."""
        text = source("src/scripts/mixar/modules/scribble_mark/ui/mark_lifecycle.py")
        assert "load_post" in text
        assert "reset_running_guard" in text
        assert "overlay.remove" in text


# =============================================================================
# Resolution honesty
# =============================================================================

class TestResolutionHonesty:
    def test_a_vertex_group_is_only_written_for_a_partial_selection(self):
        """When the mark encloses the whole object its name is already the
        precise handle, and an identical group is noise to reason about."""
        text = source("src/scripts/mixar/modules/scribble_mark/core/resolve.py")
        marker = text.index("def _attach_vertex_group")
        body = text[marker:marker + 900]
        assert 'partial' in body

    def test_resolution_reports_why_it_found_nothing(self):
        text = source("src/scripts/mixar/modules/scribble_mark/core/resolve.py")
        assert "empty_reason" in text
        assert "_empty(" in text

    def test_the_overlay_preview_never_writes_vertex_groups(self):
        """resolve_mark takes write_vertex_group so a preview can measure
        without leaving a trail of groups behind it."""
        text = source("src/scripts/mixar/modules/scribble_mark/core/resolve.py")
        assert "write_vertex_group=True" in text

    def test_marks_are_kept_after_send_not_cleared(self):
        """A follow-up turn refers back to them, and the groups and cameras
        they name are still live."""
        text = source("src/scripts/mixar/modules/scribble_mark/core/chat_bridge.py")
        marker = text.index("def finish_send")
        body = text[marker:marker + 900]
        assert "mark_all_sent" in body
        assert "clear(" not in body


# =============================================================================
# Attachment split
# =============================================================================

class TestFrameAttachments:
    def test_both_a_clean_and_an_annotated_frame_are_offered(self):
        """Burning the ink into the only image means every downstream
        generation faithfully reproduces the cyan loop."""
        text = source("src/scripts/mixar/modules/scribble_mark/core/chat_bridge.py")
        marker = text.index("for name in (")
        assert "annotated" in text[marker:marker + 200]
        assert "frame_name" in text[marker:marker + 200]

    def test_the_annotated_frame_is_queued_first(self):
        """Under a tight attachment cap the marked frame is the one carrying
        information the agent cannot get any other way."""
        text = source("src/scripts/mixar/modules/scribble_mark/core/chat_bridge.py")
        marker = text.index("for name in (")
        line = text[marker:text.index("\n", marker)]
        assert line.index("annotated") < line.index("frame_name")

    def test_annotation_flips_v_for_pil(self):
        """The payload is v bottom-up; PIL rows are top-down. Skipping the
        flip draws every mark mirrored across the horizon."""
        text = source("src/scripts/mixar/modules/scribble_mark/core/annotate.py")
        assert "1.0 - float(v)" in text


@pytest.mark.parametrize("path", sorted(
    p for p in MODULE.rglob("*.py")
))
def test_no_module_file_exceeds_the_line_limit(path):
    assert len(path.read_text().splitlines()) <= 500, path.name


class TestVisibleControlsAndRecovery:
    """A mode whose boundaries and recovery are invisible is the first thing
    users trip on with ink tools (arXiv:2607.21468 found exactly this: people
    could not tell which mode they were in, and asked for visible controls and
    a way to undo). The freeze consumes every pointer event over the region,
    so both have to be on screen."""

    OVERLAY = "src/scripts/mixar/modules/scribble_mark/core/overlay.py"
    MODAL = "src/scripts/mixar/modules/scribble_mark/ui/operators/mark_draw_ops.py"
    HEADER = "src/scripts/mixar/modules/space_mixie_chat/ui/header.py"

    def test_the_frozen_frame_carries_a_hint(self):
        text = source(self.OVERLAY)
        assert "_draw_hint" in text
        callback = text[text.index("def _draw_callback"):]
        assert "_draw_hint(" in callback, "the hint is defined but never drawn"

    def test_the_hint_names_the_way_out(self):
        from mixar.modules.scribble_mark.constants import (
            MARK_HINT_IDLE, MARK_HINT_MARKED,
        )
        assert "Esc" in MARK_HINT_IDLE
        assert "Esc" in MARK_HINT_MARKED

    def test_the_hint_names_the_way_back(self):
        from mixar.modules.scribble_mark.constants import MARK_HINT_MARKED
        assert "Backspace" in MARK_HINT_MARKED

    def test_undo_is_reachable_from_inside_the_freeze(self):
        """Bound in the modal rather than a keymap: the freeze already owns
        every event over the region, and a GUI keyconfig reload wipes
        C-registered keymap items."""
        text = source(self.MODAL)
        assert "BACK_SPACE" in text
        assert "_undo_last" in text

    def test_undo_prefers_the_half_drawn_stroke(self):
        """Mid-gesture, the thing the user means to take back is what is under
        the pen, not the mark they already finished."""
        text = source(self.MODAL)
        body = text[text.index("def _undo_last"):]
        body = body[:body.index("\n    def ", 1)]
        assert body.index("self._strokes") < body.index("remove_last")

    def test_queued_marks_can_be_cleared_without_re_arming(self):
        text = source(self.HEADER)
        assert "mixar.scribble_mark_clear" in text
        assert "not armed" in text


class TestReviewFindings:
    """Regressions found by adversarial review of the diff. Each of these is
    invisible in this suite's mocked world and only shows up in Blender, which
    is exactly why they are pinned at the source level."""

    MODAL = "src/scripts/mixar/modules/scribble_mark/ui/operators/mark_draw_ops.py"
    FREEZE = "src/scripts/mixar/modules/scribble_mark/core/freeze.py"
    OVERLAY = "src/scripts/mixar/modules/scribble_mark/core/overlay.py"

    def test_the_modal_is_bound_to_the_window_owning_the_viewport(self):
        """The Agent Bubble is its own wmWindow. Blender binds a modal to
        CTX_wm_window(C) and dispatches each window's events only against its
        own handlers, so arming from the bubble without an override registers
        the modal where no viewport event will ever arrive: nothing is
        captured, Esc does nothing, and the freeze blocks no input at all."""
        finder = source("src/scripts/mixar/modules/scribble_mark/core/freeze_session.py")
        signature = finder[finder.index("def find_view3d"):]
        signature = signature[:signature.index("return best")]
        assert "window" in signature

        text = source(self.MODAL)
        invoke = text[text.index("def invoke"):text.index("def modal")]
        assert "window, area, region = find_view3d" in invoke
        assert "temp_override(window=window" in invoke
        assert "window=window" in invoke, "the timer must be on that window too"

    def test_the_capture_override_names_the_window(self):
        """An area/region override that disagrees with the context window is
        not a coherent context."""
        text = source(self.FREEZE)
        assert "temp_override(window=window, area=area, region=region)" in text

    def test_arming_refuses_in_camera_view(self):
        """In camera view the region shows the camera frame letterboxed inside
        it while render.opengl captures only that frame, so a mark's region
        coordinates correspond to no position in the still."""
        invoke = source(self.MODAL)
        invoke = invoke[invoke.index("def invoke"):invoke.index("def modal")]
        assert "CAMERA" in invoke
        assert "CANCELLED" in invoke

    def test_media_type_is_set_before_and_restored_after_the_format(self):
        """Blender 5 rejects PNG on a scene whose output is FFMPEG until the
        media type is IMAGE — so arming would die on any scene that has been
        through a video render. The restore order mirrors the set order."""
        text = source(self.FREEZE)
        assert "media_type" in text
        set_media = text.index('settings.media_type = "IMAGE"')
        set_format = text.index('settings.file_format = "PNG"')
        assert set_media < set_format
        restore = text[text.index("finally:"):]
        assert restore.index('settings.media_type = saved["media_type"]') < \
               restore.index('settings.file_format = saved["file_format"]')

    def test_frames_are_named_per_freeze_not_recycled(self):
        """A fixed name means re-arming silently repoints an image an earlier
        chat message (and the backend's attachment_names) already refers to."""
        text = source(self.FREEZE)
        assert "def frame_name(serial)" in text
        assert "def annotated_name(serial)" in text
        session = source("src/scripts/mixar/modules/scribble_mark/core/freeze_session.py")
        assert "freeze.frame_name(serial)" in session

    def test_the_overlay_paints_only_the_frozen_viewport(self):
        """A POST_PIXEL handler on SpaceView3D runs for EVERY 3D viewport, so
        without this the still of one is stretched over all of them —
        including ones that are still live and navigable."""
        text = source(self.OVERLAY)
        assert "def set_target" in text
        callback = text[text.index("def _draw_callback"):]
        assert "_target_area_ptr" in callback
        assert "as_pointer()" in callback

    def test_a_region_resize_takes_a_new_freeze(self):
        """Once the region and the still disagree, neither size is right:
        the arm-time size mismaps the mark onto the stretched still the user
        drew on, and the live size pairs it with a raycast through a view the
        still no longer depicts. So the freeze is replaced, and marks already
        committed keep the view they were drawn on."""
        text = source(self.MODAL)
        assert "_refreeze_if_resized" in text
        timer = text[text.index('if event.type == "TIMER":'):]
        assert timer.index("_refreeze_if_resized") < timer.index("_maybe_commit")

        session = source("src/scripts/mixar/modules/scribble_mark/core/freeze_session.py")
        assert "def matches" in session
        assert "def take" in session

    def test_a_freeze_still_referenced_by_a_mark_is_not_released(self):
        """A mark drawn before a resize is still going to be sent, and its
        still and camera have to survive until it is."""
        session = source("src/scripts/mixar/modules/scribble_mark/core/freeze_session.py")
        take = session[session.index("def take"):session.index("def matches")]
        assert "view_used" in take
        release = session[session.index("def release_if_unused"):]
        assert "if self.view_used" in release

    def test_the_per_turn_cap_counts_drafts_only(self):
        """Counting every mark ever made lets eight SENT marks disable the
        feature for the rest of the .blend's life."""
        assert "drafts_only=True" in source(self.MODAL)
        marks = source("src/scripts/mixar/modules/scribble_mark/core/marks.py")
        add = marks[marks.index("def add_mark"):marks.index("def mark_all_sent")]
        assert "STATE_DRAFT" in add

    def test_every_exit_path_clears_the_armed_flag(self):
        text = source(self.MODAL)
        cancel = text[text.index("def cancel"):]
        cancel = cancel[:cancel.index("\n    # --")]
        assert "_disarm" in cancel

    def test_an_unused_freeze_is_released(self):
        """Every arm/disarm that commits no mark would otherwise add a still
        AND a camera to the .blend."""
        text = source(self.MODAL)
        finish = text[text.index("def _finish"):]
        assert "release_if_unused" in finish[:700]

        session = source("src/scripts/mixar/modules/scribble_mark/core/freeze_session.py")
        release = session[session.index("def release_if_unused"):]
        assert "view_bake.release" in release
        assert "freeze.release" in release


class TestOneScribbleMode:
    """Handwriting over the chat becomes text, ink over the viewport becomes
    marks, and the two halves enter and leave together. Pinned at the source
    level because every seam here is a Blender operator or a wmTimer."""

    MODAL = "src/scripts/mixar/modules/scribble_mark/ui/operators/mark_draw_ops.py"
    ARM = "src/scripts/mixar/modules/scribble_mark/ui/operators/mark_arm_ops.py"
    BRIDGE = "src/scripts/mixar/modules/scribble_mark/core/chat_bridge.py"
    LIFECYCLE = "src/scripts/mixar/modules/scribble_mark/ui/mark_lifecycle.py"
    INK = "src/scripts/mixar/modules/space_mixie_chat/core/scribble.py"
    INK_OPS = "src/scripts/mixar/modules/space_mixie_chat/ui/operators/ink_ops.py"
    HEADERS = (
        "src/scripts/mixar/modules/space_mixie_chat/ui/header.py",
        "src/scripts/mixar/modules/agent_bubble/ui/header.py",
    )

    def test_there_is_exactly_one_scribble_control(self):
        """Two grease-pencil buttons — one for text, one for marks — is the
        two-mode UI this feature exists to remove."""
        for header in self.HEADERS:
            text = source(header)
            assert text.count("mixar.scribble_toggle") == 1, header
            assert "toggle_scribble" not in text, header
            assert "scribble_mark_toggle" not in text, header
        assert "toggle_scribble" not in source(self.INK_OPS)

    def test_the_toggle_arms_and_disarms_through_the_coordinator(self):
        text = source(self.ARM)
        body = text[text.index("class MIXAR_OT_scribble_toggle"):text.index("class MIXAR_OT_scribble_mark_undo")]
        assert "scribble_mode.arm(" in body
        assert "scribble_mode.disarm(" in body

    def test_the_control_shows_either_half_as_armed(self):
        for header in self.HEADERS:
            text = source(header)
            block = text[text.index("mixar.scribble_toggle") - 600:text.index("mixar.scribble_toggle")]
            assert "mixar_mark_armed" in block and "mixie_chat_ink_visible" in block, header

    def test_the_freeze_passes_timer_events_through(self):
        """A window-level modal that swallows every TIMER starves the chat
        canvas's idle-commit timer: with a docked chat in the same window,
        handwriting would never convert while the viewport was frozen."""
        text = source(self.MODAL)
        timer = text[text.index('if event.type == "TIMER":'):text.index("# Undo, reachable")]
        assert 'return {"PASS_THROUGH"}' in timer
        assert 'return {"RUNNING_MODAL"}' not in timer

    def test_the_freeze_follows_the_canvas_down(self):
        """Esc or the close X over the chat canvas are C++ paths the modal
        never sees; it polls the flag on its timer instead."""
        text = source(self.MODAL)
        invoke = text[text.index("def invoke"):text.index("def modal")]
        assert "_ink_linked = scribble_mode.ink_open" in invoke
        timer = text[text.index('if event.type == "TIMER":'):text.index("# Undo, reachable")]
        assert "_ink_linked and not scribble_mode.ink_open" in timer

    def test_every_freeze_exit_lowers_the_canvas(self):
        text = source(self.MODAL)
        finish = text[text.index("def _finish"):]
        assert "scribble_mode.close_ink" in finish[:1200]

    def test_the_send_waits_for_handwriting_before_the_empty_check(self):
        """A prompt written entirely by hand is EMPTY until its last batch
        lands; bouncing it as empty throws away what the user wrote."""
        text = source(CHAT_OPS)
        execute = text[text.index("def execute"):]
        assert execute.index("flush_pending_ink") < execute.index("Cannot send empty message")
        assert execute.index("defer_until_idle") < execute.index("Cannot send empty message")

    def test_the_send_leaves_both_halves(self):
        text = source(self.BRIDGE)
        body = text[text.index("def finish_send"):text.index("# ====")]
        assert "scribble_mode.disarm" in body
        assert "mixar_mark_armed = False" not in body, "the coordinator owns the flag"

    def test_closing_the_canvas_converts_first(self):
        text = source(self.INK)
        body = text[text.index("def close_canvas"):]
        assert body.index("flush_pending_ink()") < body.index("mixie_chat_ink_visible = False")

    def test_a_file_load_drops_the_recognition_queue(self):
        assert "scribble.reset_state()" in source(self.LIFECYCLE)


class TestSharedViewCamera:
    """The baked camera belongs to a FREEZE, not to a mark. Releasing it with
    any one mark leaves its siblings pointing at a deleted camera — and
    render_viewport(view="mark") then silently renders the scene camera and
    reports it as the frame the user drew on."""

    class _Item:
        def __init__(self, view_name):
            self.view_name = view_name
            self.mark_json = "{}"

    def _shared(self, item, collection):
        from mixar.modules.scribble_mark.core.marks import _view_shared
        return _view_shared(item, collection)

    def test_a_camera_used_by_a_sibling_is_kept(self):
        a, b = self._Item("cam1"), self._Item("cam1")
        assert self._shared(a, [a, b]) is True

    def test_the_last_mark_of_a_freeze_releases_its_camera(self):
        a = self._Item("cam1")
        assert self._shared(a, [a]) is False

    def test_a_different_freeze_does_not_keep_it_alive(self):
        a, b = self._Item("cam1"), self._Item("cam2")
        assert self._shared(a, [a, b]) is False

    def test_no_collection_means_do_not_guess(self):
        assert self._shared(self._Item("cam1"), None) is False
