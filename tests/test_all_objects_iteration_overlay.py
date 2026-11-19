# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Pins `src/source/blender/python/intern/bpy_rna.cc`, upstream's file plus the
hunk fenced by `/* MIXAR-1978 begin */ ... /* MIXAR-1978 end */`
(mixar-backend#1978). A script that changed collection membership inside
`for o in coll.all_objects:` crashed the app in `Collection_all_objects_next`:
the native iterator walks the collection's cached Base list, and any link,
unlink or delete frees that cache while the iterator already points at the
next node (on macOS the freed nodes read as end-of-list, so the loop silently
stopped after two objects).

The hunk makes `pyrna_prop_collection_iter` return an iterator over a snapshot
of the RNA wrappers for `Collection.all_objects` only; ID free invalidates a
wrapper, so a deleted object's entry raises ReferenceError instead of reading
freed memory. Pinned: the property-pointer validity check runs before the type
check (it only catches a cleared pointer, so it does not guard an
`all_objects` wrapper whose collection was freed), the scope is Collection +
`all_objects`, a failed snapshot returns NULL before `PyObject_GetIter`, and
the snapshot list is released. Delete the hunk once
upstream snapshots or guards all_objects iteration. Replayed in the app by
`tests/qa/all_objects_iteration_e2e.py`."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REL = "source/blender/python/intern/bpy_rna.cc"
OVERLAY = ROOT / "src" / REL
# A linked worktree (`<checkout>/.worktrees/<name>`) has no submodule checkout of
# its own; read the main checkout's, as `settings.sh` does.
UPSTREAM_CANDIDATES = (
    ROOT / "upstream" / REL,
    ROOT.parents[1] / "upstream" / REL,
)
MIXAR_SPDX = " * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited\n"
MARKED = re.compile(r"[ \t]*/\* MIXAR-1978 begin \*/\n.*?[ \t]*/\* MIXAR-1978 end \*/\n", re.S)


def _block() -> str:
    blocks = MARKED.findall(OVERLAY.read_text(encoding="utf-8"))
    assert len(blocks) == 1
    return blocks[0]


def _ordered(text: str, *parts: str) -> bool:
    positions = [text.find(part) for part in parts]
    return -1 not in positions and positions == sorted(positions)


def test_the_hunk_sits_in_collection_iter_before_the_native_iterator():
    text = OVERLAY.read_text(encoding="utf-8")
    # The last definition is the `USE_PYRNA_ITER` one (defined in bpy_rna.hh); the
    # earlier `#ifndef USE_PYRNA_ITER` fallback is compiled out.
    start = text.rindex("static PyObject *pyrna_prop_collection_iter(PyObject *self)\n")
    body = text[start:text.index("\n}\n", start)]
    assert _ordered(body, "/* MIXAR-1978 begin */", "/* MIXAR-1978 end */",
                    "return pyrna_prop_collection_iter_CreatePyObject(")


def test_only_collection_all_objects_iterates_a_snapshot():
    block = _block()
    assert _ordered(block, "PYRNA_PROP_CHECK_OBJ(self_property);", "RNA_struct_is_a")
    assert "RNA_struct_is_a(self_property->ptr->type, RNA_Collection)" in block
    assert 'STREQ(RNA_property_identifier(self_property->prop), "all_objects")' in block
    assert _ordered(block, "pyrna_prop_collection_values(self_property)",
                    "if (values == nullptr) {\n      return nullptr;",
                    "PyObject_GetIter(values)", "Py_DECREF(values);", "return iter;")


def test_the_overlay_is_upstream_plus_the_marked_hunk():
    """Keep the change fenced so an upstream bump is a re-copy plus re-apply."""
    upstream = next((p for p in UPSTREAM_CANDIDATES if p.exists()), None)
    if upstream is None:
        pytest.skip("upstream submodule not checked out")
    ov = OVERLAY.read_text(encoding="utf-8")
    assert ov.count("/* MIXAR-1978 begin */") == ov.count("/* MIXAR-1978 end */") == 1
    assert MIXAR_SPDX in ov
    unpatched = MARKED.sub("", ov.replace(MIXAR_SPDX, "", 1))
    if unpatched != upstream.read_text(encoding="utf-8"):
        pytest.fail(
            "upstream bpy_rna.cc changed, or an overlay edit is not fenced: re-copy the "
            "upstream file and re-apply the MIXAR-1978 hunk (or delete it if upstream now "
            "guards Collection.all_objects iteration)",
            pytrace=False,
        )
