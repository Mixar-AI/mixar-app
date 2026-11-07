# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""`bpy.data.temp_data()` must hand its `as` target a reference of its own.

At the pinned Blender, `__enter__` returned the context manager's reference
without adding one, so the target dangled once the context manager was freed
and a later allocation or GC pass crashed (mixar-backend#1847, in the
executor's scene capture after an agent script used `temp_data()`). The
overlay is upstream's file plus upstream 9b217bcbd65, fffc34b8571 and
45756ac053d, verbatim; the running-app check is
`tests/qa/temp_data_context_ref_e2e.py`."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "src/source/blender/python/intern/bpy_rna_data.cc"
UPSTREAM = ROOT / "upstream/source/blender/python/intern/bpy_rna_data.cc"

NEW_REF = "return Py_NewRef(reinterpret_cast<PyObject *>(self->data_rna));"
OLD_REF = "return reinterpret_cast<PyObject *>(self->data_rna);"
ADDED_BLOCKS = (
    "  ret->data_rna = nullptr;\n",
    "  if (self->data_rna != nullptr) {\n"
    '    PyErr_SetString(PyExc_RuntimeError, "Context manager already entered");\n'
    "    return nullptr;\n  }\n\n",
    "  /* Only possible when `__exit__` is called directly instead of via a `with` statement. */\n"
    "  if (self->data_rna == nullptr) {\n"
    '    PyErr_SetString(PyExc_RuntimeError, "Context manager not entered");\n'
    "    return nullptr;\n  }\n",
    "  if (self->data_rna->ptr->data == nullptr) {\n"
    '    PyErr_SetString(PyExc_RuntimeError, "Context manager already exited");\n'
    "    return nullptr;\n  }\n\n",
)


def _strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def test_enter_returns_a_new_reference():
    text = OVERLAY.read_text(encoding="utf-8")
    assert NEW_REF in text and OLD_REF not in text


def test_misuse_guards_are_present():
    text = OVERLAY.read_text(encoding="utf-8")
    for block in ADDED_BLOCKS:
        assert text.count(block) == 1, block


def test_the_overlay_is_upstream_plus_the_backported_hunks():
    """Keep the overlay a verbatim backport so a pin bump just deletes it."""
    if not UPSTREAM.exists():
        return
    up = UPSTREAM.read_text(encoding="utf-8")
    if NEW_REF in up:
        return  # the pin already carries the fix: delete the overlay
    ov = OVERLAY.read_text(encoding="utf-8").replace(NEW_REF, OLD_REF)
    for block in ADDED_BLOCKS:
        ov = ov.replace(block, "")
    assert _strip_comments(ov) == _strip_comments(up)
