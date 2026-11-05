# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""`mesh.edges.add(n)` / `loops.add(n)` / `polygons.add(n)` must default-fill
exactly the n new elements. At our Blender pin the edge/corner/face helpers in
`mesh_data.cc` passed the count `n` as the END of the fill range
(`IndexRange::from_begin_end(old_size, len)`): with `n < old_size` the range had
a negative size and the fill ran out of bounds (mixar-backend#1858, an agent
script adding loops to a 47k-corner mesh crashed in `fill_segment`). The overlay
is upstream's fix 56a6f5b4ac backported; drop it once the pin includes it.
Replayed in the app by `tests/qa/mesh_add_elements_e2e.py`."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "src/source/blender/editors/mesh/mesh_data.cc"
# A linked worktree (`<checkout>/.worktrees/<name>`) has no submodule checkout of
# its own; read the main checkout's, as `settings.sh` does.
UPSTREAM_CANDIDATES = (
    ROOT / "upstream/source/blender/editors/mesh/mesh_data.cc",
    ROOT.parents[1] / "upstream/source/blender/editors/mesh/mesh_data.cc",
)
DOMAINS = ("Point", "Edge", "Corner", "Face")
MIXAR_SPDX = " * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited\n"


def _strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/\n?", "", text, flags=re.S)


def test_every_add_helper_fills_a_begin_size_range():
    text = _strip_comments(OVERLAY.read_text(encoding="utf-8"))
    assert "from_begin_end(old_size, len)" not in text
    for domain in DOMAINS:
        call = f"bke::AttrDomain::{domain}, {{}}, IndexRange::from_begin_size(old_size, len));"
        assert text.count(call) == 1, domain


def test_the_overlay_only_differs_from_upstream_in_the_three_ranges():
    """Keep the overlay a three-line patch so an upstream bump is a re-copy."""
    upstream = next((p for p in UPSTREAM_CANDIDATES if p.exists()), None)
    if upstream is None:
        return
    up = upstream.read_text(encoding="utf-8")
    if "from_begin_end(old_size, len)" not in up:
        return  # the pin already carries 56a6f5b4ac: the overlay can go
    ov = OVERLAY.read_text(encoding="utf-8").replace(MIXAR_SPDX, "", 1)
    patched = up.replace("from_begin_end(old_size, len)", "from_begin_size(old_size, len)")
    assert _strip_comments(patched) == _strip_comments(ov)
