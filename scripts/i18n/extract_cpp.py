# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""C/C++ half of the message extractor (a small tokenizer, not a compiler).

Collected, mirroring what Blender's own extractor treats as translatable:

* ``IFACE_`` ``TIP_`` ``RPT_`` ``DATA_`` ``N_`` and their ``CTX_*`` forms
* report calls: ``BKE_report[f]`` ``WM_global_report[f]`` ``WM_report[f]``
  (the first string literal — the format when it is ``*f``)
* ``ot->name`` / ``ot->description`` assignments (context from a literal or
  ``BLT_I18NCONTEXT_*`` ``ot->translation_context`` in the same function)
* RNA UI text: ``RNA_def_property_ui_text``, ``RNA_def_struct_ui_text`` and
  the ``RNA_def_<type>`` helpers (their last two string literals after the
  identifier are the UI name and description)
* ``EnumPropertyItem`` initializers ``{value, "ID", icon, "Name", "Tip"}``

Text a Mixar widget draws from a bare literal is invisible here — wrap it in
``IFACE_``/``TIP_``/``RPT_`` where it is drawn, which also translates it.
"""

from __future__ import annotations

import re
from pathlib import Path

from i18n_common import MessageSet

MACROS = {"IFACE_": "label", "TIP_": "tooltip", "RPT_": "report", "DATA_": "data",
          "N_": "label"}
CTX_MACROS = {"CTX_IFACE_": "label", "CTX_TIP_": "tooltip", "CTX_RPT_": "report",
              "CTX_DATA_": "data", "CTX_N_": "label"}
REPORT_FUNCS = {"BKE_report", "BKE_reportf", "WM_global_report", "WM_global_reportf",
                "WM_report", "WM_reportf", "BKE_report_format"}
RNA_SKIP = {"RNA_def_property", "RNA_def_struct", "RNA_def_function", "RNA_def_parameter_flags",
            "RNA_def_property_flag", "RNA_def_struct_sdna", "RNA_def_property_sdna",
            "RNA_def_function_ui_description", "RNA_def_function_return",
            "RNA_def_function_flag", "RNA_def_property_ui_text", "RNA_def_struct_ui_text",
            "RNA_def_property_update", "RNA_def_property_enum_items",
            "RNA_def_property_translation_context", "RNA_def_struct_translation_context"}

_TOKEN = re.compile(
    r'(?P<ws>\s+)|(?P<lc>//[^\n]*)|(?P<bc>/\*.*?\*/)'
    r'|(?P<str>(?:u8|u|U|L)?"(?:[^"\\\n]|\\.)*")|(?P<rstr>(?:u8|u|U|L)?R"(?P<delim>[^(]*)\(.*?\)(?P=delim)")'
    r'|(?P<chr>\'(?:[^\'\\\n]|\\.)*\')|(?P<ident>[A-Za-z_]\w*)|(?P<num>\d[\w.]*)'
    r'|(?P<punct>->|::|.)',
    re.S | re.M,
)
_SIMPLE_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "'": "'", "0": "\0",
                   "a": "\a", "b": "\b", "f": "\f", "v": "\v", "?": "?"}


def _unescape(body: str) -> str:
    if "\\" not in body:
        return body
    raw = body.encode("utf-8")
    buf = bytearray()
    i = 0
    while i < len(raw):
        if raw[i:i + 1] == b"\\" and i + 1 < len(raw):
            nxt = chr(raw[i + 1])
            if nxt == "x":
                m = re.match(rb"[0-9A-Fa-f]{1,2}", raw[i + 2:])
                if m:
                    buf.append(int(m.group(0), 16))
                    i += 2 + len(m.group(0))
                    continue
            elif nxt in "01234567":
                m = re.match(rb"[0-7]{1,3}", raw[i + 1:])
                buf.append(int(m.group(0), 8))
                i += 1 + len(m.group(0))
                continue
            elif nxt in "uU":
                n = 4 if nxt == "u" else 8
                buf.extend(chr(int(raw[i + 2:i + 2 + n], 16)).encode("utf-8"))
                i += 2 + n
                continue
            buf.extend(_SIMPLE_ESCAPES.get(nxt, nxt).encode("utf-8"))
            i += 2
            continue
        buf.append(raw[i])
        i += 1
    return buf.decode("utf-8", errors="replace")


def tokenize(source: str):
    """``[(kind, value, line)]`` with adjacent string literals concatenated."""
    tokens = []
    line = 1
    for m in _TOKEN.finditer(source):
        kind = m.lastgroup
        text = m.group(0)
        if kind in ("str", "rstr"):
            if kind == "str":
                value = _unescape(text[text.index('"') + 1:-1])
            else:
                delim = m.group("delim")
                start = text.index('R"') + 2 + len(delim) + 1
                value = text[start:len(text) - len(delim) - 2]
            if tokens and tokens[-1][0] == "str":
                tokens[-1] = ("str", tokens[-1][1] + value, tokens[-1][2])
            else:
                tokens.append(("str", value, line))
        elif kind in ("ident", "num", "punct", "chr"):
            tokens.append((kind, text, line))
        line += text.count("\n")
    return tokens


def _args(tokens, open_idx):
    """Top-level arguments of the call whose ``(`` is at ``open_idx``."""
    depth = 0
    args, cur = [], []
    for i in range(open_idx, len(tokens)):
        kind, value, _line = tokens[i]
        if value in "([{" and kind == "punct":
            depth += 1
            if depth == 1:
                continue
        elif value in ")]}" and kind == "punct":
            depth -= 1
            if depth == 0:
                args.append(cur)
                return args, i
        if depth == 1 and kind == "punct" and value == ",":
            args.append(cur)
            cur = []
            continue
        cur.append(tokens[i])
    return args, len(tokens) - 1


def _ternary_literals(arg) -> list:
    """Both branches of ``cond ? "a" : "b"`` when they are literals."""
    depth = 0
    question = colon = None
    for j, (kind, value, _line) in enumerate(arg):
        if kind == "punct" and value in "([{":
            depth += 1
        elif kind == "punct" and value in ")]}":
            depth -= 1
        elif depth == 0 and kind == "punct" and value == "?" and question is None:
            question = j
        elif depth == 0 and kind == "punct" and value == ":" and question is not None:
            colon = j
    if question is None or colon is None:
        return []
    out = [_literal(arg[question + 1:colon]), _literal(arg[colon + 1:])]
    return [text for text in out if text is not None]


def _literal(arg):
    """The string of an argument that is a literal or ``N_("...")``."""
    if len(arg) == 1 and arg[0][0] == "str":
        return arg[0][1]
    if len(arg) == 4 and arg[0][1] in ("N_",) and arg[2][0] == "str":
        return arg[2][1]
    if len(arg) >= 6 and arg[0][1] == "CTX_N_" and arg[-2][0] == "str":
        return arg[-2][1]
    return None


def _context(arg, contexts):
    if len(arg) == 1 and arg[0][0] == "str":
        return arg[0][1]
    if len(arg) == 1 and arg[0][0] == "ident":
        return contexts.get(arg[0][1])
    return None


def load_contexts(*headers: Path) -> dict[str, str]:
    """``BLT_I18NCONTEXT_*`` macro -> context string from translation headers."""
    out = {"BLT_I18NCONTEXT_DEFAULT": None, "BLT_I18NCONTEXT_DEFAULT_BPYRNA": None,
           "BLT_I18NCONTEXT_OPERATOR_DEFAULT": "Operator"}
    for header in headers:
        if header and header.is_file():
            for name, value in re.findall(r'#define\s+(BLT_I18NCONTEXT_\w+)\s+"([^"]*)"',
                                          header.read_text(encoding="utf-8", errors="replace")):
                out[name] = value
    return out


def _is_api_parameter(arg) -> bool:
    """RNA function parameters (``func``/``parm``) are Python API docs, not UI."""
    return len(arg) == 1 and arg[0][1] in ("func", "parm")


def _function_blocks(tokens) -> list[int]:
    """Per token, the index of the top-level brace block it sits in (-1 outside)."""
    out = []
    depth = 0
    block = -1
    for i, (kind, value, _line) in enumerate(tokens):
        if kind == "punct" and value == "{":
            if depth == 0:
                block = i
            depth += 1
        out.append(block if depth else -1)
        if kind == "punct" and value == "}":
            depth = max(0, depth - 1)
    return out


def _operator_contexts(tokens, blocks, contexts) -> dict[int, str | None]:
    """Block -> context of an ``ot->translation_context = X`` inside it."""
    out = {}
    for i in range(len(tokens) - 4):
        if tokens[i][1] == "ot" and tokens[i + 1][1] == "->" \
                and tokens[i + 2][1] == "translation_context" and tokens[i + 3][1] == "=":
            out[blocks[i]] = _context([tokens[i + 4]], contexts)
    return out


def extract_source(source: str, ref: str, contexts: dict | None = None) -> MessageSet:
    contexts = contexts or {}
    messages = MessageSet()
    tokens = tokenize(source)
    blocks = _function_blocks(tokens)
    op_contexts = _operator_contexts(tokens, blocks, contexts)
    n = len(tokens)
    for i, (kind, value, _line) in enumerate(tokens):
        nxt = tokens[i + 1][1] if i + 1 < n else ""
        if kind == "ident" and nxt == "(":
            if value in MACROS:
                args, _ = _args(tokens, i + 1)
                if len(args) == 1 and len(args[0]) == 1 and args[0][0][0] == "str":
                    messages.add(args[0][0][1], MACROS[value], ref)
            elif value in CTX_MACROS:
                args, _ = _args(tokens, i + 1)
                if len(args) == 2 and len(args[1]) == 1 and args[1][0][0] == "str":
                    messages.add(args[1][0][1], CTX_MACROS[value], ref,
                                 _context(args[0], contexts))
            elif value in REPORT_FUNCS:
                args, _ = _args(tokens, i + 1)
                for arg in args:
                    texts = [_literal(arg)] if _literal(arg) is not None else _ternary_literals(arg)
                    if texts:
                        for text in texts:
                            messages.add(text, "report", ref)
                        break
            elif value in ("RNA_def_property_ui_text", "RNA_def_struct_ui_text"):
                args, _ = _args(tokens, i + 1)
                if len(args) == 3 and not _is_api_parameter(args[0]):
                    messages.add(_literal(args[1]), "property", ref)
                    messages.add(_literal(args[2]), "tooltip", ref)
            elif value.startswith("RNA_def_") and value not in RNA_SKIP:
                args, _ = _args(tokens, i + 1)
                if args and _is_api_parameter(args[0]):
                    continue
                strings = [_literal(a) for a in args[2:]]
                strings = [s for s in strings if s is not None]
                if len(strings) >= 2:
                    messages.add(strings[-2], "property", ref)
                    messages.add(strings[-1], "tooltip", ref)
            elif value in ("STRNCPY", "STRNCPY_UTF8", "BLI_strncpy"):
                args, _ = _args(tokens, i + 1)
                target = "".join(t[1] for t in args[0]) if args else ""
                if target.endswith(("->label", "->category", ".label", ".category")) \
                        and len(args) >= 2:
                    messages.add(_literal(args[1]), "label", ref)
        elif kind == "ident" and value == "ot" and nxt == "->" and i + 4 < n \
                and tokens[i + 3][1] == "=" and tokens[i + 2][1] in ("name", "description"):
            field = tokens[i + 2][1]
            rhs_end = i + 4
            while rhs_end < n and tokens[rhs_end][1] != ";":
                rhs_end += 1
            text = _literal(tokens[i + 4:rhs_end])
            if text is None and rhs_end - (i + 4) == 4 and tokens[i + 4][1] in ("IFACE_", "TIP_"):
                text = tokens[i + 6][1] if tokens[i + 6][0] == "str" else None
            if field == "name":
                messages.add(text, "label", ref, op_contexts.get(blocks[i]))
            else:
                messages.add(text, "tooltip", ref)
        if kind == "punct" and value == "{":
            _enum_item(tokens, i, messages, ref)
    return messages


def _enum_item(tokens, idx, messages, ref) -> None:
    args, _end = _args(tokens, idx)
    # Exactly five non-empty members, the first a value (not a string): a
    # trailing comma in a plain string array would otherwise look like one.
    if len(args) != 5 or any(not arg for arg in args) or args[0][0][0] == "str":
        return
    ident = _literal(args[1])
    if ident is None or not re.fullmatch(r"[\w.\-]+", ident or "-"):
        return
    name, desc = _literal(args[3]), _literal(args[4])
    null = ("nullptr", "NULL", "")
    if name is None and "".join(t[1] for t in args[3]) not in null:
        return
    if desc is None and "".join(t[1] for t in args[4]) not in null:
        return
    if name:
        messages.add(name, "enum", ref)
    if desc:
        messages.add(desc, "tooltip", ref)


def extract_file(path: Path, ref: str, contexts: dict | None = None) -> MessageSet:
    return extract_source(path.read_text(encoding="utf-8", errors="replace"), ref, contexts)
