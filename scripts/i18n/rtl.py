# SPDX-FileCopyrightText: 2012-2026 Blender Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Right-to-left pre-processing for catalogs, as Blender does for its own.

Blender's text engine (BLF) does no bidi reordering or Arabic shaping, so
Blender stores its ``ar_EG``/``fa_IR``/``he_IL``/``ur`` catalogs in VISUAL
order with Arabic presentation forms (``_bl_i18n_utils/utils_rtl.py``).
Mixar's catalogs for those languages must be stored the same way, or they
render reversed and unjoined. Translators write normal (logical) text;
``translation_batches.py import`` converts it with ``log2vis`` below.

Adapted from Blender's ``scripts/modules/_bl_i18n_utils/utils_rtl.py``
(fribidi through ctypes; format sequences are protected with LRE/PDF so
``{name}`` / ``%s`` keep their order). Unlike Blender, multi-line messages
are processed line by line — fribidi reorders a single line.
Requires the fribidi shared library (``libfribidi.so.0`` on Linux,
``libfribidi.0.dylib`` via Homebrew on macOS, ``$MIXAR_FRIBIDI_LIB``).
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import re

RTL_LANGUAGES = frozenset({"ar_EG", "fa_IR", "he_IL", "ur"})

FRIBIDI_PAR_ON = 0x00000040
FRIBIDI_FLAG_SHAPE_MIRRORING = 0x00000001
FRIBIDI_FLAG_REORDER_NSM = 0x00000002
FRIBIDI_FLAG_REMOVE_SPECIALS = 0x00040000
FRIBIDI_FLAG_SHAPE_ARAB_PRES = 0x00000100
FRIBIDI_FLAG_SHAPE_ARAB_LIGA = 0x00000200
FRIBIDI_FLAGS = (FRIBIDI_FLAG_SHAPE_MIRRORING | FRIBIDI_FLAG_REORDER_NSM
                 | FRIBIDI_FLAG_REMOVE_SPECIALS | FRIBIDI_FLAG_SHAPE_ARAB_PRES
                 | FRIBIDI_FLAG_SHAPE_ARAB_LIGA)

LRE = "‪"
PDF = "‬"

_FIELD = re.compile(r"\{(?:[A-Za-z_]\w*(?:\.[A-Za-z_]\w*|\[\w+\])*|\d*)(?:![rsa])?(?::[^{}]*)?\}")
_PRINTF_FLAGS = set("-+ #0")
_WIDTHPREC = set(".0123456789")
_DATASIZE = set("hljztL")
_PRINTF_CODES = set("diuoxXfFeEgGaAcsp")


def _library():
    candidates = [os.environ.get("MIXAR_FRIBIDI_LIB"), "libfribidi.so.0",
                  "libfribidi.0.dylib", "/opt/homebrew/lib/libfribidi.0.dylib",
                  "/usr/local/lib/libfribidi.0.dylib", "libfribidi-0.dll",
                  ctypes.util.find_library("fribidi")]
    for name in candidates:
        if not name:
            continue
        try:
            return ctypes.CDLL(name)
        except OSError:
            continue
    raise RuntimeError("fribidi not found: install it (apt install libfribidi0 / brew install "
                       "fribidi) or set MIXAR_FRIBIDI_LIB")


def protect_format_seq(msg: str) -> str:
    """Wrap ``{name:spec}``, ``%s``-style and escape sequences in LRE..PDF."""
    idx = 0
    out = []
    ln = len(msg)
    while idx < ln:
        dlt = 1
        if idx < ln - 1 and msg[idx] == "\\" and msg[idx + 1] in "\"'\\":
            dlt = 2
        elif idx < ln - 1 and msg[idx:idx + 2] in ("{{", "}}"):
            dlt = 2
        elif idx < ln - 1 and msg[idx] == "{":
            # A whole replacement field, whatever its format spec ("{faces:,}").
            field = _FIELD.match(msg, idx)
            if field:
                dlt = field.end() - idx
        elif idx < ln - 1 and msg[idx] == "%" and msg[idx + 1] == "%":
            dlt = 2
        elif idx < ln - 1 and msg[idx] == "%":
            j = idx + 1
            while j < ln and msg[j] in _PRINTF_FLAGS:
                j += 1
            while j < ln and msg[j] in _WIDTHPREC:
                j += 1
            while j < ln and msg[j] in _DATASIZE:
                j += 1
            if j < ln and msg[j] in _PRINTF_CODES:
                dlt = j + 1 - idx
        if dlt > 1:
            out.append(LRE)
        out.append(msg[idx:idx + dlt])
        if dlt > 1:
            out.append(PDF)
        idx += dlt
    return "".join(out)


def _log2vis_line(fbd, line: str) -> str:
    if not line:
        return line
    buf = ctypes.create_unicode_buffer(protect_format_seq(line))
    ln = len(buf) - 1
    btypes = (ctypes.c_int * ln)()
    embed_lvl = (ctypes.c_uint8 * ln)()
    pbase_dir = ctypes.c_int(FRIBIDI_PAR_ON)
    jtypes = (ctypes.c_uint8 * ln)()
    fbd.fribidi_get_bidi_types(buf, ln, ctypes.byref(btypes))
    fbd.fribidi_get_par_embedding_levels(btypes, ln, ctypes.byref(pbase_dir), embed_lvl)
    fbd.fribidi_get_joining_types(buf, ln, jtypes)
    fbd.fribidi_join_arabic(btypes, ln, embed_lvl, jtypes)
    fbd.fribidi_shape(FRIBIDI_FLAGS, embed_lvl, ln, jtypes, buf)
    fbd.fribidi_reorder_line(FRIBIDI_FLAGS, btypes, ln, 0, pbase_dir, embed_lvl, buf, None)
    # REMOVE_SPECIALS blanks the explicit marks out; drop what is left of them.
    return buf.value.replace(LRE, "").replace(PDF, "")


def log2vis(msg: str) -> str:
    """Logical-order text -> the visual, shaped form Blender stores."""
    fbd = _library()
    return "\n".join(_log2vis_line(fbd, line) for line in msg.split("\n"))


def is_visual(msg: str) -> bool:
    """Heuristic: Arabic-script text already carries presentation forms."""
    return any("ﭐ" <= ch <= "﷿" or "ﹰ" <= ch <= "﻿" for ch in msg)
