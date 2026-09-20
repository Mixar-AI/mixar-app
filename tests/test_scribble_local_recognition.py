# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scribble's instant path: on-device recognition first, the backend after.

Handwriting reached the composer 0.85 s of idle plus a 1–6 s vision-LLM round
trip after the pen lifted. Two changes: the idle commit is shorter and more
batches travel at once, and on macOS every batch is first read by the
platform recogniser (Apple Vision, ~100–300 ms, offline) — the backend only
sees batches the local reading refuses, fails on, or is not confident about.
Ordering is untouched: text still enters the composer strictly in the order
it was written.

The queue is pure Python (`LocalRecognitionQueue`); the C++/ObjC halves are
pinned at source level.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

CHAT = ROOT / "src/source/blender/editors/space_mixie_chat"
INK_INTERN_HH = (CHAT / "mixie_chat_ink_intern.hh").read_text(encoding="utf-8")
SPACE_CC = (CHAT / "space_mixie_chat.cc").read_text(encoding="utf-8")
CHAT_CMAKE = (CHAT / "CMakeLists.txt").read_text(encoding="utf-8")
LOCAL_CC = (CHAT / "mixie_chat_ink_local.cc").read_text(encoding="utf-8")
VISION_MM = (ROOT / "src/intern/ghost/intern/GHOST_MixarVisionCocoa.mm").read_text(encoding="utf-8")
GHOST_CMAKE = (ROOT / "src/intern/ghost/CMakeLists.txt").read_text(encoding="utf-8")
SCRIBBLE_PY = (ROOT / "src/scripts/mixar/modules/space_mixie_chat/core/scribble.py").read_text(encoding="utf-8")
CONSTANTS_PY = (ROOT / "src/scripts/mixar/modules/space_mixie_chat/constants.py").read_text(encoding="utf-8")


# `space_mixie_chat.core/__init__.py` imports the connection manager (and so
# auth -> keyring), none of which the standalone suite has. Seed a light
# package object so the two pure modules under test import as submodules
# without executing that init — their own relative imports only reach
# `..constants` (bpy-free) and lazily `.scribble`.
import types  # noqa: E402

_CORE_PKG = "mixar.modules.space_mixie_chat.core"
if _CORE_PKG not in sys.modules:
    _pkg = types.ModuleType(_CORE_PKG)
    _pkg.__path__ = [str(SCRIPTS / "mixar" / "modules" / "space_mixie_chat" / "core")]
    _pkg.__package__ = _CORE_PKG
    sys.modules[_CORE_PKG] = _pkg

from mixar.modules.space_mixie_chat import constants as C  # noqa: E402
from mixar.modules.space_mixie_chat.core.scribble_local import (  # noqa: E402
    LocalRecognitionQueue,
    accept,
    prepare_vision_image,
    vision_page_geometry,
)


class _Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def _queue(results=None, refuse=False, timeout=2.5):
    submitted = []
    pending = list(results or [])

    def submit(job, image_bytes):
        submitted.append((job, image_bytes))
        return not refuse

    def pop():
        return pending.pop(0) if pending else None

    clock = _Clock()
    q = LocalRecognitionQueue(submit, pop, now_fn=clock, timeout_s=timeout)
    return q, submitted, pending, clock


# ---------------------------------------------------------------------------
# Queue behaviour
# ---------------------------------------------------------------------------


def test_refused_submission_reports_false_so_the_caller_posts_to_the_backend():
    q, submitted, _, _ = _queue(refuse=True)
    assert q.submit(b"png", lambda *a: None) is False
    assert submitted == [(1, b"png")]
    assert q.pending == 0


def test_a_landed_result_reaches_its_callback():
    q, _, pending, _ = _queue()
    got = []
    assert q.submit(b"png", lambda t, c, ok: got.append((t, c, ok)))
    pending.append((1, "hello", 0.9, True))
    assert q.pump() is False
    assert got == [("hello", 0.9, True)]


def test_results_for_unknown_jobs_are_ignored():
    q, _, pending, _ = _queue()
    got = []
    q.submit(b"png", lambda *a: got.append(a))
    pending.append((99, "stale", 0.9, True))
    assert q.pump() is True  # job 1 still outstanding
    assert got == []


def test_a_batch_that_never_returns_fails_at_its_deadline():
    q, _, _, clock = _queue(timeout=2.5)
    got = []
    q.submit(b"png", lambda t, c, ok: got.append((t, c, ok)))
    clock.t += 2.0
    assert q.pump() is True and got == []
    clock.t += 1.0
    assert q.pump() is False
    assert got == [("", 0.0, False)]


def test_reset_fails_everything_outstanding():
    q, _, _, _ = _queue()
    got = []
    q.submit(b"a", lambda t, c, ok: got.append(ok))
    q.submit(b"b", lambda t, c, ok: got.append(ok))
    q.reset()
    assert got == [False, False] and q.pending == 0


def test_a_failing_callback_does_not_stall_the_queue():
    q, _, pending, _ = _queue()

    def boom(*a):
        raise RuntimeError("handler")

    got = []
    q.submit(b"a", boom)
    q.submit(b"b", lambda t, c, ok: got.append(t))
    pending.extend([(1, "x", 0.9, True), (2, "y", 0.9, True)])
    assert q.pump() is False
    assert got == ["y"]


# ---------------------------------------------------------------------------
# Acceptance
# ---------------------------------------------------------------------------


def test_acceptance_needs_text_and_confidence():
    assert accept("hello", C.SCRIBBLE_LOCAL_MIN_CONFIDENCE)
    assert not accept("hello", C.SCRIBBLE_LOCAL_MIN_CONFIDENCE - 0.01)
    assert not accept("", 1.0), "an empty local reading is exactly what the stronger model should see"
    assert not accept("   ", 1.0)


# ---------------------------------------------------------------------------
# Page framing for the recogniser
# ---------------------------------------------------------------------------


def test_short_tall_ink_is_scaled_down_to_a_text_line_with_margins():
    """The app raster of 'HI' is 1328x979: two glyphs filling the frame, which
    Vision reads as line art. Framed as a ~120 px line it reads."""
    page = vision_page_geometry(1328, 979)
    assert abs(979 * page.scale - C.SCRIBBLE_LOCAL_LINE_HEIGHT_PX) < 1
    assert page.offset_x == C.SCRIBBLE_LOCAL_PAGE_PAD_X and page.offset_y == C.SCRIBBLE_LOCAL_PAGE_PAD_Y
    assert page.page_h == C.SCRIBBLE_LOCAL_LINE_HEIGHT_PX + 2 * C.SCRIBBLE_LOCAL_PAGE_PAD_Y


def test_a_long_line_is_capped_by_width_not_height():
    page = vision_page_geometry(9000, 600)
    assert page.page_w == C.SCRIBBLE_LOCAL_MAX_WIDTH_PX + 2 * C.SCRIBBLE_LOCAL_PAGE_PAD_X
    assert 600 * page.scale < C.SCRIBBLE_LOCAL_LINE_HEIGHT_PX


def test_small_ink_is_never_upscaled():
    page = vision_page_geometry(80, 40)
    assert page.scale == 1.0
    assert (page.page_w, page.page_h) == (80 + 2 * C.SCRIBBLE_LOCAL_PAGE_PAD_X, 40 + 2 * C.SCRIBBLE_LOCAL_PAGE_PAD_Y)


def test_prepare_vision_image_frames_real_pixels():
    from io import BytesIO

    from PIL import Image, ImageDraw

    big = Image.new("L", (1300, 900), 255)
    ImageDraw.Draw(big).rectangle((100, 100, 1200, 800), outline=16, width=30)
    buf = BytesIO()
    big.save(buf, format="PNG")
    framed = Image.open(BytesIO(prepare_vision_image(buf.getvalue()))).convert("L")
    bbox = Image.eval(framed, lambda v: 255 if v < 128 else 0).getbbox()
    assert bbox is not None
    ink_h = bbox[3] - bbox[1]
    assert abs(ink_h - C.SCRIBBLE_LOCAL_LINE_HEIGHT_PX) <= 2
    assert bbox[0] >= C.SCRIBBLE_LOCAL_PAGE_PAD_X - 1 and bbox[1] >= C.SCRIBBLE_LOCAL_PAGE_PAD_Y - 1


def test_prepare_vision_image_returns_the_input_when_it_cannot_frame():
    assert prepare_vision_image(b"not a png") == b"not a png"


def test_submission_writes_the_framed_copy():
    src = (ROOT / "src/scripts/mixar/modules/space_mixie_chat/core/scribble_local.py").read_text(encoding="utf-8")
    submit = src[src.index("def _submit_via_operator(") :]
    submit = submit[: submit.index("\ndef ")]
    assert "handle.write(prepare_vision_image(image_bytes))" in submit


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


def test_scribble_tries_local_first_and_falls_back_to_the_backend():
    start = SCRIBBLE_PY[SCRIBBLE_PY.index("def _start(") :]
    start = start[: start.index("\ndef _finish(")]
    assert "_try_local(" in start
    assert "scribble_local.accept(" in start
    # Both outcomes of the local attempt are covered: accepted -> finish, else backend.
    on_local = start[start.index("def _on_local("):]
    assert "_finish(seq, _clean_recognized(text), None)" in on_local
    assert on_local.index("_finish(seq, _clean_recognized(text), None)") < on_local.index("_post_backend()")
    assert "_post(image_bytes, _hint_for(scene), _on_success, _on_error)" in start


def test_idle_commit_is_shorter_and_lockstep_across_languages():
    cpp = re.search(r"INK_IDLE_COMMIT_SEC = ([0-9.]+);", INK_INTERN_HH)
    py = re.search(r"^SCRIBBLE_IDLE_COMMIT_MS = (\d+)", CONSTANTS_PY, re.M)
    assert cpp and py
    assert abs(float(cpp.group(1)) * 1000 - int(py.group(1))) < 1
    assert float(cpp.group(1)) <= 0.5
    step = re.search(r"INK_IDLE_TIMER_STEP = ([0-9.]+);", INK_INTERN_HH)
    assert step and float(step.group(1)) < float(cpp.group(1))
    assert C.SCRIBBLE_MAX_IN_FLIGHT >= 3


def test_local_recognition_operators_are_registered_and_built():
    for op in ("MIXIE_CHAT_OT_ink_recognize_local", "MIXIE_CHAT_OT_ink_local_poll"):
        assert f"void {op}(wmOperatorType *ot)" in LOCAL_CC
        assert f"WM_operatortype_append({op});" in SPACE_CC
    assert "mixie_chat_ink_local.cc" in CHAT_CMAKE
    # The capability IS the start operator's poll — Python keeps no platform table.
    assert "ot->poll = ink_recognize_local_poll;" in LOCAL_CC
    assert "#else\n  return false;\n#endif" in LOCAL_CC


def test_vision_helper_is_runtime_loaded_and_built():
    assert "dlopen(" in VISION_MM and "NSClassFromString(" in VISION_MM
    # No link-time class reference: every Vision class comes from NSClassFromString.
    assert "[VNRecognizeTextRequest " not in VISION_MM
    assert "[VNImageRequestHandler " not in VISION_MM
    assert "VNRequestTextRecognitionLevelAccurate" in VISION_MM
    assert "intern/GHOST_MixarVisionCocoa.mm" in GHOST_CMAKE
    # Results only ever cross into Blender by being popped on the main thread.
    assert 'extern "C" bool Mixar_VisionPopResult(' in VISION_MM
