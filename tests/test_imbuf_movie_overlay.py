# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""`imbuf.mixar_movie_frames` (the context-folder video decoder) lives in its
own overlay TU, `imbuf_mixar_movie.cc`, and hooks into upstream's
`imbuf_py_api.cc` through exactly two lines — a forward declaration and the
register call — so an upstream bump is a re-copy plus those two lines. The
decoder runs on the RPC worker thread, so it must stay pure imbuf/movie:
no Main, RNA, GPU or window-manager access."""

import difflib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERIC = "source/blender/python/generic"
OVERLAY_API = ROOT / "src" / GENERIC / "imbuf_py_api.cc"
UPSTREAM_API = ROOT / "upstream" / GENERIC / "imbuf_py_api.cc"
MOVIE = ROOT / "src" / GENERIC / "imbuf_mixar_movie.cc"
CMAKE = ROOT / "src" / GENERIC / "CMakeLists.txt"


def test_the_overlay_api_differs_from_upstream_only_by_the_two_hook_lines():
    if not UPSTREAM_API.exists():
        return
    up = UPSTREAM_API.read_text(encoding="utf-8").splitlines()
    ov = OVERLAY_API.read_text(encoding="utf-8").splitlines()
    diff = list(difflib.unified_diff(up, ov, lineterm="", n=0))
    removed = [line for line in diff[2:] if line.startswith("-")]
    added = [line[1:] for line in diff[2:] if line.startswith("+")]
    assert removed == [], removed
    assert set(added) == {"", "void mixar_movie_register(PyObject *module);", "  mixar_movie_register(mod);"}
    assert added.count("void mixar_movie_register(PyObject *module);") == 1
    assert added.count("  mixar_movie_register(mod);") == 1
    # The call sits in BPyInit_imbuf, right before the module is returned.
    text = OVERLAY_API.read_text(encoding="utf-8")
    assert "  mixar_movie_register(mod);\n\n  return mod;\n}" in text


def test_the_decoder_is_a_gil_releasing_pure_imbuf_function():
    text = MOVIE.read_text(encoding="utf-8")
    for needle in ("Py_BEGIN_ALLOW_THREADS", "Py_END_ALLOW_THREADS", "MOV_open_file(",
                   "MOV_decode_frame(", "IMB_flipy(", "MOV_close(", "IMB_scale(",
                   "IMB_byte_from_float(", "IMB_freeImBuf(", "PyModule_AddFunctions(",
                   '"mixar_movie_frames"', "namespace blender"):
        assert needle in text, needle
    for banned in ("BKE_", "RNA_", "GPU_", "WM_", "DNA_ID"):
        assert banned not in text, banned
    assert len(text.splitlines()) < 200


def test_the_overlay_cmake_builds_the_decoder_against_the_movie_library():
    text = CMAKE.read_text(encoding="utf-8")
    assert "  imbuf_mixar_movie.cc\n" in text
    assert "  PRIVATE bf::imbuf\n" in text
    assert "  PRIVATE bf::imbuf::movie\n" in text
