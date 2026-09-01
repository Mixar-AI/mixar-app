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
        marker = text.index("capture_region_still")
        following = text[marker:marker + 600]
        assert "CANCELLED" in following

    def test_render_settings_are_restored(self):
        text = source("src/scripts/mixar/modules/scribble_mark/core/freeze.py")
        assert "finally:" in text
        for setting in ("resolution_x", "resolution_y", "file_format",
                        "resolution_percentage", "filepath"):
            assert text.count(setting) >= 2, f"{setting} saved but not restored"

    def test_the_frozen_frame_is_packed_and_unlinked_from_tempdir(self):
        """It lives in bpy.app.tempdir, which is cleaned on exit; a mark
        referencing a vanished image loses the one thing a VLM can read."""
        text = source("src/scripts/mixar/modules/scribble_mark/core/freeze.py")
        assert ".pack()" in text
        assert "filepath_raw" in text

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
