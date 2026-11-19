# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Pins `src/source/blender/blenkernel/intern/mesh_normals.cc`, upstream's file
plus the hunk fenced by `/* MIXAR-2041 begin */ ... /* MIXAR-2041 end */` in
`collect_corner_info` (mixar-backend#2041).

A face that uses a vertex twice (`[a, b, c, b]`, which `from_pydata` accepts
unvalidated) is listed once per corner in `vert_to_face_map[b]`, the entries
adjacent in the sorted group. Upstream resolved every entry with
`face_find_corner_from_vert`, which returns the FIRST corner of the vertex, so
the other corner never joined a fan: its `corner_space_indices` entry stayed
uninitialized and its normal was never written. The Weighted Normal modifier
and `mesh_normals_corner_custom_set` (`normals_split_custom_set`) then indexed
arrays with that garbage index and crashed. The hunk gives each repeated entry
the next corner of the vertex after the previous entry's corner.

Delete the hunk once upstream fixes `collect_corner_info`. Replayed in the app
by the QA harness (AP-2041, `scenarios/custom_normals_repeated_vertex_e2e.py`)."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "src/source/blender/blenkernel/intern/mesh_normals.cc"
# A linked worktree (`<checkout>/.worktrees/<name>`) has no submodule checkout of
# its own; read the main checkout's, as `settings.sh` does.
UPSTREAM_CANDIDATES = (
    ROOT / "upstream/source/blender/blenkernel/intern/mesh_normals.cc",
    ROOT.parents[1] / "upstream/source/blender/blenkernel/intern/mesh_normals.cc",
)
MIXAR_SPDX = " * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited\n"
MARKED = re.compile(r"[ \t]*/\* MIXAR-2041 begin \*/\n.*?[ \t]*/\* MIXAR-2041 end \*/\n", re.S)
# The upstream statement the fenced block replaces.
UPSTREAM_STATEMENT = (
    "    r_corner_infos[i].corner = face_find_corner_from_vert(faces[face], corner_verts, vert);\n"
)


def _function(text: str, name: str) -> str:
    start = text.index(f" {name}(")
    start = text.rindex("\n", 0, start) + 1
    return text[start:text.index("\n}\n", start) + 3]


def _hunk(text: str) -> str:
    match = MARKED.search(text)
    assert match, "the MIXAR-2041 hunk is missing"
    return match.group(0)


def _ordered(text: str, *parts: str) -> bool:
    positions = [text.find(part) for part in parts]
    return -1 not in positions and positions == sorted(positions)


def test_repeated_entries_take_the_next_corner_of_the_vertex():
    ov = OVERLAY.read_text(encoding="utf-8")
    assert ov.count("/* MIXAR-2041 begin */") == ov.count("/* MIXAR-2041 end */") == 1
    hunk = _hunk(ov)
    assert hunk in _function(ov, "collect_corner_info")
    code = re.sub(r"/\*.*?\*/", "", hunk, flags=re.S)
    assert _ordered(
        code,
        "if (i > 0 && face == vert_faces[i - 1])",
        "r_corner_infos[i - 1].corner + 1",
        "first_index_try(vert)",
        "face_find_corner_from_vert(faces[face], corner_verts, vert)",
    )
    # A stale map with no later corner falls back to the first corner, never a sentinel.
    assert code.count("face_find_corner_from_vert(") == 2
    # Every other entry (all of them on a valid mesh) keeps upstream's statement.
    assert "    else {\n  " + UPSTREAM_STATEMENT + "    }\n" in code


def test_no_sentinel_space_index():
    """A -1 space index reached MOD_weighted_normal and mesh_mirror as an array index."""
    ov = OVERLAY.read_text(encoding="utf-8")
    assert "fill(-1)" not in ov
    assert "contains(-1)" not in ov


def test_the_overlay_is_upstream_plus_the_marked_hunk():
    """Keep the change fenced so an upstream bump is a re-copy plus re-apply."""
    upstream = next((p for p in UPSTREAM_CANDIDATES if p.exists()), None)
    if upstream is None:
        pytest.skip("upstream submodule not checked out")
    up = upstream.read_text(encoding="utf-8")
    if UPSTREAM_STATEMENT not in _function(up, "collect_corner_info"):
        pytest.fail(
            "upstream changed collect_corner_info: if it now gives each repeat of a vertex in a "
            "face its own corner (mixar-backend#2041), delete the overlay; otherwise re-copy the "
            "file and re-apply the MIXAR-2041 hunk"
        )
    ov = OVERLAY.read_text(encoding="utf-8")
    assert MIXAR_SPDX in ov
    unpatched = MARKED.sub(UPSTREAM_STATEMENT, ov.replace(MIXAR_SPDX, "", 1), count=1)
    if unpatched != up:
        old, new = unpatched.splitlines(), up.splitlines()
        line = next((i for i, pair in enumerate(zip(old, new)) if pair[0] != pair[1]), min(len(old), len(new)))
        pytest.fail(
            "upstream mesh_normals.cc changed (first difference at upstream line "
            f"{line + 1}), or an overlay edit is not fenced: re-copy the upstream file and "
            "re-apply the MIXAR-2041 hunk",
            pytrace=False,
        )
