# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""A failed immediate-mode buffer mapping must not crash the app.

Upstream `GLImmediate::begin` returns whatever `glMapBufferRange` gives back and
only asserts it in debug builds. On AMD Windows OpenGL drivers it has returned
null, and the next `immVertex*` wrote to address 0 (crash reports from three
users: the agent bubble's frost wash and the view3d gizmo buttons). The overlay
retries the mapping on fresh storage, once per streak of failures; without a
mapping after that it hands out scratch memory for that primitive and skips its
draw in `end()`.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "src/source/blender/gpu/opengl/gl_immediate.cc"
# A linked worktree (`<checkout>/.worktrees/<name>`) has no submodule checkout of
# its own; read the main checkout's, as `settings.sh` does.
UPSTREAM_CANDIDATES = (
    ROOT / "upstream/source/blender/gpu/opengl/gl_immediate.cc",
    ROOT.parents[1] / "upstream/source/blender/gpu/opengl/gl_immediate.cc",
)

MAP_CALL = "glMapBufferRange(GL_ARRAY_BUFFER, buffer_offset(), bytes_needed, access);"
RETRY_MAP_CALL = "glMapBufferRange(GL_ARRAY_BUFFER, buffer_offset, bytes_needed, access);"
GUARD = re.compile(r"\n  if \(map_failed\) \{\n(.*?)\n  \}\n", re.S)
# The retry: everything between the gate and the brace that closes it.
RETRY = re.compile(r"\n  if \(bytes_needed > 0 && !map_retry_spent\) \{\n(.*?)\n  \}\n", re.S)
# File-scope state: `static <specifiers> map_<name>[ = <value>];`.
STATE = re.compile(r"^static ([^\n(]*?) ?\b(map_\w+)(?: = [^;\n]*)?;$", re.M)


def _code(text: str) -> str:
    """The text without comments, so prose never satisfies an assertion."""
    return re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", text, flags=re.S))


def _fn(text: str, signature: str) -> str:
    start = text.index(signature)
    return _code(text[start : text.index("\n}\n", start)])


def _assert_in_order(text: str, *needles: str) -> None:
    pos = 0
    for needle in needles:
        found = text.find(needle, pos)
        assert found != -1, f"missing, or before the previous step: {needle!r}"
        pos = found + len(needle)


def test_begin_retries_on_fresh_storage_before_handing_out_scratch():
    text = OVERLAY.read_text(encoding="utf-8")
    begin = _fn(text, "uchar *GLImmediate::begin()")
    _assert_in_order(
        begin,
        "void *data = " + MAP_CALL,
        "if (data == nullptr) {",
        "data = map_failure_fallback(buffer_size(), buffer_offset(), bytes_needed, access);",
        # The fallback must come before the pointer is handed to immVertex*.
        "return static_cast<uchar *>(data);",
    )
    assert begin.count("glMapBufferRange(") == 1
    fallback = _fn(text, "static void *map_failure_fallback(")
    _assert_in_order(
        fallback,
        # By reference: the retry maps the fresh store from 0, and end() draws from that offset.
        "size_t &buffer_offset,",
        # A zero-length mapping is null by specification: it must not orphan the buffer.
        "if (bytes_needed > 0 &&",
        # Fresh storage also unmaps a buffer that was left mapped.
        "glBufferData(GL_ARRAY_BUFFER, store_size, nullptr, GL_DYNAMIC_DRAW);",
        "buffer_offset = 0;",
        "void *data = " + RETRY_MAP_CALL,
        "if (data != nullptr) {",
        "return data;",
        # Scratch only after the retry has failed too.
        "map_failed = true;",
        "map_scratch.resize((bytes_needed + sizeof(float) - 1) / sizeof(float));",
        "return map_scratch.data();",
    )
    # One retry, and one place that hands out scratch.
    assert fallback.count("glBufferData(") == 1
    assert fallback.count("glMapBufferRange(") == 1
    assert fallback.count("map_failed = true;") == 1
    assert fallback.count("map_scratch") == 2
    assert "map_failed" not in begin and "map_scratch" not in begin
    # immVertex* writes floats and 32-bit ints: an inline uchar buffer is not aligned for them.
    assert "static thread_local Vector<float, 0> map_scratch;" in text


def test_the_failure_state_is_per_thread():
    """Job threads draw with GL contexts of their own. With a shared flag, one thread's failed
    mapping would skip another thread's draw and its own end() would draw unmapped storage."""
    code = _code(OVERLAY.read_text(encoding="utf-8"))
    assert {name: specifiers for specifiers, name in STATE.findall(code)} == {
        "map_failure_logged": "thread_local bool",
        "map_failed": "thread_local bool",
        "map_retry_spent": "thread_local bool",
        "map_scratch": "thread_local Vector<float, 0>",
    }


def test_the_retry_is_spent_once_per_streak_of_failures():
    """A driver that fails every mapping must not get a fresh 4 MiB store on every immBegin."""
    text = OVERLAY.read_text(encoding="utf-8")
    fallback = _fn(text, "static void *map_failure_fallback(")
    retry = RETRY.search(fallback)
    assert retry, "the retry needs a top-level `if (bytes_needed > 0 && !map_retry_spent) {`"
    # Spent before the orphan, and both retry calls are inside the gate, nowhere else.
    _assert_in_order(retry.group(1), "map_retry_spent = true;", "glBufferData(", RETRY_MAP_CALL)
    for call in ("glBufferData(", "glMapBufferRange("):
        assert retry.group(1).count(call) == fallback.count(call) == 1, call
    # A retry that recovers ends the streak...
    assert (
        "    if (data != nullptr) {\n      map_retry_spent = false;\n      return data;\n    }"
        in retry.group(1)
    )
    assert fallback.count("map_retry_spent") == 3
    # ...and so does a first mapping that succeeds; a null goes to the fallback.
    begin = _fn(text, "uchar *GLImmediate::begin()")
    _assert_in_order(
        begin,
        "void *data = " + MAP_CALL,
        "  if (data == nullptr) {\n"
        "    data = map_failure_fallback(buffer_size(), buffer_offset(), bytes_needed, access);\n"
        "  }\n"
        "  else {\n"
        "    map_retry_spent = false;\n"
        "  }\n",
        "return static_cast<uchar *>(data);",
    )
    assert begin.count("map_retry_spent") == 1
    # Nothing else touches the flag: clearing it in end() would retry on every failing draw.
    assert _code(text).count("map_retry_spent") == 5


def test_the_one_log_line_reads_the_buffer_before_the_orphan():
    """After glBufferData the buffer is unmapped and has the expected size: nothing to learn."""
    fallback = _fn(OVERLAY.read_text(encoding="utf-8"), "static void *map_failure_fallback(")
    _assert_in_order(
        fallback,
        "const bool log = !map_failure_logged;",
        "map_failure_logged = true;",
        "if (log) {",
        "glGetBufferParameteriv(GL_ARRAY_BUFFER, GL_BUFFER_MAPPED, &gl_mapped);",
        "glGetBufferParameteriv(GL_ARRAY_BUFFER, GL_BUFFER_SIZE, &gl_size);",
        # Read before the retry, so the next error is the retry's own.
        "stale_error = glGetError();",
        "glBufferData(",
        RETRY_MAP_CALL,
        "if (log) {",
        "retry_error = glGetError();",
        "CLOG_ERROR(",
        "if (data != nullptr) {",
    )
    assert fallback.count("CLOG_ERROR(") == 1
    assert fallback.count("glGetError()") == 2


def test_end_skips_unmap_and_draw_after_a_failed_mapping():
    end = _fn(OVERLAY.read_text(encoding="utf-8"), "void GLImmediate::end()")
    guard = GUARD.search(end)
    assert guard, "end() needs a top-level `if (map_failed) {` block"
    # Clear the flag and leave: nothing else, and never without the return.
    statements = [line.strip() for line in guard.group(1).splitlines() if line.strip()]
    assert statements == ["map_failed = false;", "return;"]
    assert end.count("map_failed") == 2
    # Nothing was mapped, so the guard precedes every call that touches the mapping or draws it.
    for call in ("glFlushMappedBufferRange(", "glUnmapBuffer(", "glDrawArrays("):
        assert call in end, call
        assert guard.end() <= end.index(call), f"the guard must come before {call}"


def test_upstream_lines_survive_in_order_and_the_hunks_are_marked():
    """Every upstream line but the debug-only assert is still there, in upstream's order, and the
    overlay carries `MIXAR-2043` markers. Lines added between them are not checked."""
    upstream = next((p for p in UPSTREAM_CANDIDATES if p.exists()), None)
    if upstream is None:
        pytest.skip("upstream submodule not checked out")
    up = upstream.read_text(encoding="utf-8").splitlines()
    ov = OVERLAY.read_text(encoding="utf-8").splitlines()
    kept = [line for line in up if line.strip() != "BLI_assert(data != nullptr);"]
    it = iter(ov)
    assert all(any(line == other for other in it) for line in kept)
    assert len(re.findall(r"MIXAR-2043", "\n".join(ov))) >= 3
