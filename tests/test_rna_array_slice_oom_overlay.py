# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Pins the `MIXAR-2144` hunks in `src/source/blender/python/intern/bpy_rna.cc`.

`pyrna_prop_array_subscript_slice` turns an RNA array into a Python tuple; it
backs `list(prop)`, `prop[:]` and iteration. Upstream checks none of its
allocations: `PyTuple_New`, the `PyMem_MALLOC` scratch buffer, or each
`PyFloat_FromDouble` / `PyBool_FromLong` / `PyLong_FromLong`. An agent script ran
`px = list(img.pixels)` on a 4096x4096 texture (67M floats, about 2.5 GB of Python
objects) on a 7 GB laptop; an allocation returned NULL and the app crashed in
python313.dll (mixar-backend#2144) instead of raising `MemoryError`. The hunks
return NULL with the error set at each failure point.

Replayed in the app with a job-object memory cap on the QA process: the
unfixed build crashes, the fixed one raises MemoryError and keeps running."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "src/source/blender/python/intern/bpy_rna.cc"
HUNK = re.compile(r"/\* MIXAR-2144 begin \*/\n(.*?)[ \t]*/\* MIXAR-2144 end \*/", re.S)
SIGNATURE = "static PyObject *pyrna_prop_array_subscript_slice(BPy_PropertyArrayRNA *self,\n"


def _definition() -> str:
    text = OVERLAY.read_text(encoding="utf-8").replace("\r\n", "\n")
    start = text.index(SIGNATURE, text.index(SIGNATURE) + 1)  # skip the forward declaration
    return text[start : text.index("\n}\n", start)]


def test_every_hunk_is_in_the_slice_function():
    text = OVERLAY.read_text(encoding="utf-8").replace("\r\n", "\n")
    body = _definition()
    assert len(HUNK.findall(text)) == len(HUNK.findall(body)) == 5


def test_a_failed_tuple_allocation_returns_before_it_is_used():
    body = _definition()
    new = body.index("  tuple = PyTuple_New(slice_length);\n")
    check = body.index("  if (tuple == nullptr) {\n    return nullptr;\n  }\n", new)
    first_use = body.index("RNA_property_array_dimension", new)
    assert new < check < first_use


def test_each_scratch_buffer_is_checked_before_rna_fills_it():
    body = _definition()
    for ctype, getter in (("float", "RNA_property_float_get_array"),
                          ("bool", "RNA_property_boolean_get_array"),
                          ("int", "RNA_property_int_get_array")):
        alloc = body.index(f"values = static_cast<{ctype} *>(PyMem_MALLOC(sizeof({ctype}) * array_length));")
        check = body.index("if (values == nullptr) {\n            Py_DECREF(tuple);\n"
                           "            return PyErr_NoMemory();\n          }", alloc)
        fill = body.index(getter, alloc)
        assert alloc < check < fill, ctype


def test_a_tuple_with_a_failed_item_is_never_returned():
    body = _definition()
    scan = body.rindex("if (PyTuple_GET_ITEM(tuple, count) == nullptr) {")
    assert scan < body.rindex("  return tuple;")
    assert "return PyErr_Occurred() ? nullptr : PyErr_NoMemory();" in body[scan:]
