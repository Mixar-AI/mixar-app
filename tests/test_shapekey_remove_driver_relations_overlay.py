# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Pins `src/source/blender/blenkernel/intern/object.cc`: upstream's file plus a
backport of upstream 023dcaed86e (Fix #166663), fenced by
`/* MIXAR-2065 begin */ ... /* MIXAR-2065 end */` and the line tagged
`/* MIXAR-2065 */`.

`BKE_object_shapekey_remove` deletes the removed key's drivers from the Key's
AnimData but at our pin never rebuilt depsgraph relations, so the stale driver
nodes stayed in the graph. `Object.shape_key_remove` from Python (an MCP agent
script removing driven shape keys, mixar-backend#2065) followed by any
evaluation then crashed in `BKE_animsys_eval_driver`. Drop the overlay once the
pin carries 023dcaed86e. Replayed in the app by the QA harness (AP-2065)."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "src/source/blender/blenkernel/intern/object.cc"
# A linked worktree (`<checkout>/.worktrees/<name>`) has no submodule checkout of
# its own; read the main checkout's, as `settings.sh` does.
UPSTREAM_CANDIDATES = (
    ROOT / "upstream/source/blender/blenkernel/intern/object.cc",
    ROOT.parents[1] / "upstream/source/blender/blenkernel/intern/object.cc",
)
MIXAR_SPDX = " * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited\n"
MARKED = re.compile(r"[ \t]*/\* MIXAR-2065 begin \*/\n.*?[ \t]*/\* MIXAR-2065 end \*/\n", re.S)
TAGGED = re.compile(r"^[^\n]*/\* MIXAR-2065 \*/\n", re.M)
REMOVE_DRIVERS = "  BKE_animdata_drivers_remove_for_rna_struct(key->id, *RNA_ShapeKey, kb);\n"


def _shapekey_remove_body(text: str) -> str:
    start = text.index("bool BKE_object_shapekey_remove(Main *bmain, Object *ob, KeyBlock *kb)\n{")
    return text[start : text.index("\n}\n", start)]


def test_removing_a_shape_key_rebuilds_relations_after_dropping_its_drivers():
    body = _shapekey_remove_body(OVERLAY.read_text(encoding="utf-8"))
    after = body[body.index(REMOVE_DRIVERS) + len(REMOVE_DRIVERS) :]
    hunk = after[: after.index("/* MIXAR-2065 end */")]
    assert "  DEG_relations_tag_update(bmain);\n" in hunk


def test_the_overlay_only_differs_from_upstream_in_the_marked_hunk():
    """Keep the overlay a one-line patch so an upstream bump is a re-copy."""
    upstream = next((p for p in UPSTREAM_CANDIDATES if p.exists()), None)
    if upstream is None:
        pytest.skip("no upstream checkout")
    up = upstream.read_text(encoding="utf-8")
    if "DEG_relations_tag_update" in _shapekey_remove_body(up):
        pytest.fail("the pin carries upstream 023dcaed86e: delete the object.cc overlay (mixar-backend#2065)")
    ov = OVERLAY.read_text(encoding="utf-8")
    assert MIXAR_SPDX in ov
    ov = TAGGED.sub("", MARKED.sub("", ov.replace(MIXAR_SPDX, "", 1)))
    assert ov == up
