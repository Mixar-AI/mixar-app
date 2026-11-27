# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Pins the MIXAR-2031 ID-property wrapper liveness overlays (mixar-backend#2031).

Python wrappers of ID properties (`obj["group"]`, its arrays, `id_properties_ui()`)
hold raw `IDProperty *` pointers. Upstream leaves them dangling when the property
is deleted, replaced, popped or cleared, so a script that kept one read or wrote
freed memory: the app crashed at once, or the heap was corrupted and the next
depsgraph rebuild crashed in `idp_foreach_property_recurse`. The fix:

- `blenkernel/intern/idprop.cc`: upstream plus `MIXAR-2031` hunks that tell a
  release listener the address of every IDProperty struct about to be freed or
  moved (`BKE_idprop_mixar.hh`).
- `python/generic/idprop_py_liveness.{hh,cc}`: the listener; it clears every
  tracked wrapper field holding that address.
- `python/generic/idprop_py_api/*.inc`, `idprop_py_ui_api.cc`, `intern/bpy_rna.cc`:
  wrappers are tracked at creation, untracked in `tp_dealloc`, and every accessor
  raises `ReferenceError` on a cleared pointer.

The running-app proof is the QA harness scenario `idprop_dangling_e2e`.
Delete the overlays once upstream invalidates its ID-property wrappers.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src/source/blender"
MIXAR_SPDX = " * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited\n"
MARKED = re.compile(r"[ \t]*/\* MIXAR-2031 begin \*/\n.*?[ \t]*/\* MIXAR-2031 end \*/\n\n?", re.S)
TAGGED = re.compile(r"^[^\n]*/\* MIXAR-2031 \*/\n", re.M)
PARTS = SRC / "python/generic/idprop_py_api"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _upstream(rel: str):
    for base in (ROOT / "upstream", ROOT.parents[1] / "upstream"):
        path = base / "source/blender" / rel
        if path.exists():
            return _read(path)
    return None


# The one tagged line that REPLACES an upstream line rather than adding one.
DEALLOC_SLOT = re.compile(r"(/\*tp_dealloc\*/) reinterpret_cast<destructor>\(\w+\), /\* MIXAR-2031 \*/")


def _strip(text: str) -> str:
    text = DEALLOC_SLOT.sub(r"\1 nullptr,", text.replace(MIXAR_SPDX, "", 1))
    return TAGGED.sub("", MARKED.sub("", text))


def _body(text: str, signature: str) -> str:
    """The body of the definition (not a forward declaration) starting with `signature`."""
    start = 0
    while True:
        start = text.index(signature, start)
        head = text[start : start + 400]
        brace, semi = head.find("{"), head.find(";")
        if brace != -1 and (semi == -1 or brace < semi):
            return text[start : text.index("\n}\n", start)]
        start += len(signature)


@pytest.mark.parametrize("rel", ["blenkernel/intern/idprop.cc", "python/generic/idprop_py_ui_api.cc"])
def test_full_copy_overlays_only_differ_from_upstream_in_marked_hunks(rel):
    upstream = _upstream(rel)
    if upstream is None:
        pytest.skip("no upstream checkout")
    overlay = _read(SRC / rel)
    assert MIXAR_SPDX in overlay
    assert _strip(overlay) == upstream


def test_every_released_or_moved_property_struct_is_announced():
    text = _read(SRC / "blenkernel/intern/idprop.cc")
    notify = "idp_mixar_notify_release("
    # A freed property, before its struct is deleted.
    recurse = _body(text, "static void idp_free_property_recurse(IDProperty *prop,\n")
    assert recurse.index(notify) < recurse.index("MEM_delete(prop);")
    # Each group child, before the list nodes are freed.
    group = _body(text, "static void IDP_FreeGroup(")
    assert group.index(notify) < group.index("free_no_destruct()")
    # Each element of a freed IDP_IDPARRAY, before the element buffer is deleted.
    idparray = _body(text, "static void IDP_FreeIDPArray(")
    assert idparray.index(notify) < idparray.index("MEM_delete(")
    # Truncated elements (both paths) and kept elements the realloc moved.
    resize = _body(text, "void IDP_ResizeIDPArray(IDProperty *prop, int newlen)")
    assert resize.count(notify) == 3
    assert "mixar_old_elements != prop->data.pointer" in resize


def test_listener_is_cheap_and_never_dereferences():
    text = _read(SRC / "python/generic/idprop_py_liveness.cc")
    listener = _body(text, "void release_listener(const IDProperty *prop)")
    assert listener.index("tracked_num.load(") < listener.index("std::scoped_lock")
    assert "prop->" not in listener
    assert "BKE_idprop_mixar_release_listener_set(release_listener);" in text


def _parts() -> str:
    return "\n".join(_read(p) for p in sorted(PARTS.glob("part_*.inc")))


GUARDED = [
    "BPy_IDGroup_hash", "BPy_IDGroup_repr", "BPy_IDGroup_GetName", "BPy_IDGroup_SetName",
    "BPy_IDGroup_Map_Len", "BPy_IDGroup_Map_GetItem", "BPy_IDGroup_Map_SetItem",
    "BPy_IDGroup_iter", "BPy_Group_Iter_same_size_or_raise_error", "IDGroup_Iter_New_WithType",
    "BPy_Group_View_len", "BPy_IDGroup_pop", "BPy_IDGroup_keys", "BPy_IDGroup_values",
    "BPy_IDGroup_items", "BPy_IDGroup_Contains", "BPy_IDGroup_update", "BPy_IDGroup_to_dict",
    "BPy_IDGroup_clear", "BPy_IDGroup_get", "BPy_IDArray_repr", "BPy_IDArray_get_typecode",
    "BPy_IDArray_to_list", "BPy_IDArray_Len", "BPy_IDArray_GetItem", "BPy_IDArray_SetItem",
    "BPy_IDArray_slice", "BPy_IDArray_ass_slice", "BPy_IDArray_subscript",
    "BPy_IDArray_ass_subscript", "BPy_IDArray_getbuffer",
]


@pytest.mark.parametrize("func", GUARDED)
def test_every_wrapper_accessor_checks_its_pointer_first(func):
    text = _parts()
    match = re.search(r"^(?:static |PyObject \*|int )[^;\n]*\b" + func + r"\([^{]*?\n\{\n([^\n]*)\n",
                      text, re.M | re.S)
    assert match, func
    assert "/* MIXAR-2031 */" in match.group(1), f"{func} does not start with the liveness guard"


def test_wrappers_are_tracked_at_creation_and_untracked_on_dealloc():
    text = _parts()
    assert "BPy_IDProperty_liveness_track(&group->prop);" in text
    assert "BPy_IDProperty_liveness_track(&array->prop);" in text
    assert text.count("/*tp_dealloc*/ reinterpret_cast<destructor>(BPy_IDProperty_dealloc),") == 2
    assert "BPy_IDProperty_liveness_untrack(&self->prop);" in text
    assert "BPy_IDProperty_liveness_init();" in _body(text, "void IDProp_Init_Types()")
    # `group.update(other_group)` reads the other wrapper too.
    assert "BPY_IDPROP_CHECK_OBJ(other->prop);" in text

    rna = _read(SRC / "python/intern/bpy_rna.cc")
    assert "BPy_IDProperty_liveness_track(&group->prop); /* MIXAR-2031 */" in rna
    assert "BPy_IDProperty_liveness_track(&ui_manager->property); /* MIXAR-2031 */" in rna

    ui = _read(SRC / "python/generic/idprop_py_ui_api.cc")
    assert "BPy_IDProperty_liveness_untrack(&self->property);" in ui
    assert "BPY_IDPROP_CHECK_OBJ(ui_manager_src->property);" in ui
    assert ui.count("BPY_IDPROP_CHECK_OBJ(self->property);") == 4


def test_split_parts_stay_under_the_file_size_limit():
    for part in PARTS.glob("part_*.inc"):
        assert len(_read(part).splitlines()) <= 500, part.name


def test_new_sources_are_built():
    cmake = _read(SRC / "python/generic/CMakeLists.txt")
    assert "  idprop_py_liveness.cc\n" in cmake
    assert "  idprop_py_liveness.hh\n" in cmake
