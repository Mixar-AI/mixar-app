# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Cycles' kernel-cache path must be initialised thread-safely. The first
`path_cache_get()` call per process comes from every Metal shader-compile
thread at once (the first Cycles render after launch, e.g. an MCP
`render_viewport(quality="final")`), and upstream lazily assigned a file-scope
`static string` without a lock. A reader raced the writer, got a torn path,
`@(path.c_str())` yielded nil and `+[NSURL fileURLWithPath:]` aborted the app
(Mixar-2026-10-10-113235.ips). The overlay uses a function-local `static const`,
which C++11 initialises exactly once."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "src/intern/cycles/util/path.cpp"
UPSTREAM_CANDIDATES = (
    ROOT / "upstream/intern/cycles/util/path.cpp",
    ROOT.parents[1] / "mixar-texture-painting/upstream/intern/cycles/util/path.cpp",
)


def _strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def _cache_fn(text: str) -> str:
    start = text.index("string path_cache_get(")
    return text[start : text.index("\n}\n", start)]


def test_the_cache_path_is_a_once_initialised_function_local_static():
    text = OVERLAY.read_text(encoding="utf-8")
    assert "cached_xdg_cache_path" not in text, "the racy file-scope static must be gone"
    fn = _strip_comments(_cache_fn(text))
    assert "static const string xdg_cache_path = path_xdg_cache_get();" in fn
    assert "path_join(xdg_cache_path, \"cycles\")" in fn
    assert ".empty()" not in fn


def test_the_overlay_only_differs_from_upstream_in_that_function_and_declaration():
    """Keep the overlay a two-hunk patch so an upstream bump is a re-copy."""
    upstream = next((p for p in UPSTREAM_CANDIDATES if p.exists()), None)
    if upstream is None:
        return
    up = upstream.read_text(encoding="utf-8")
    ov = OVERLAY.read_text(encoding="utf-8")
    decl = "static string cached_xdg_cache_path;\n"
    up_rest = _strip_comments(up.replace(_cache_fn(up), "").replace(decl, ""))
    ov_rest = _strip_comments(ov.replace(_cache_fn(ov), ""))
    assert up_rest == ov_rest
