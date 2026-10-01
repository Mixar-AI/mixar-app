# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Python half of the message extractor (AST, no imports of the scanned code).

Collected, as the exact strings Blender looks up at runtime:

* class ``bl_label`` / ``bl_description`` / ``bl_category``, and the class
  docstring Blender uses as the description when ``bl_description`` is absent
  (cleaned the way Python 3.13's compiler cleans it — Blender 5.2's bundled
  interpreter — so the msgid equals ``__doc__``)
* ``name=`` / ``description=`` and literal ``items=`` of ``*Property(...)``
* enum-item-shaped tuples anywhere: ``("ID", "Name", "Description"[, icon[, n]])``
* ``text=`` / ``heading=`` / ``title=`` / ``message=`` / ``confirm_text=`` /
  ``placeholder=`` of any call (skipped when the call passes ``translate=False``)
* ``report(type, "message")``
* explicit markers: ``iface_`` ``tip_`` ``rpt_`` ``data_`` ``n_`` and
  ``bpy.app.translations.pgettext*`` (first argument; literal ``msgctxt``)

f-strings are invisible here on purpose: translate a template and format it.
"""

from __future__ import annotations

import ast
from pathlib import Path

from i18n_common import MessageSet

UI_KEYWORDS = ("text", "heading", "title", "message", "confirm_text", "placeholder")
MARKERS = {
    "iface_": "label", "tip_": "tooltip", "rpt_": "report", "data_": "data", "n_": "label",
    "pgettext": "label", "pgettext_iface": "label", "pgettext_tip": "tooltip",
    "pgettext_rpt": "report", "pgettext_data": "data", "pgettext_n": "label",
}
CLASS_ATTRS = {"bl_label": "label", "bl_description": "tooltip", "bl_category": "label"}


def clean_docstring(doc: str) -> str:
    """Python 3.13 ``_PyCompile_CleanDoc``: the value ``__doc__`` holds."""
    doc = doc.expandtabs()
    lines = doc.split("\n")
    margin = None
    for line in lines[1:]:
        stripped = line.lstrip(" ")
        if stripped:
            indent = len(line) - len(stripped)
            margin = indent if margin is None else min(margin, indent)
    margin = margin or 0
    out = [lines[0].lstrip(" ")]
    for line in lines[1:]:
        indent = len(line) - len(line.lstrip(" "))
        out.append(line[min(indent, margin):])
    return "\n".join(out)


def _str(node) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _strs(node) -> list[str]:
    """Literal strings a value can evaluate to: ``"A" if x else "B"``, ``x or "A"``."""
    if node is None:
        return []
    literal = _str(node)
    if literal is not None:
        return [literal]
    if isinstance(node, ast.IfExp):
        return _strs(node.body) + _strs(node.orelse)
    if isinstance(node, ast.BoolOp):
        return [text for value in node.values for text in _strs(value)]
    return []


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _is_enum_item(node) -> bool:
    if not isinstance(node, ast.Tuple) or not 3 <= len(node.elts) <= 5:
        return False
    ident, name, desc = (_str(e) for e in node.elts[:3])
    if ident is None or name is None or desc is None:
        return False
    if not ident or not ident.replace("_", "").replace("-", "").replace(".", "").isalnum():
        return False
    # An item's UI name reads like one: "Base Color", "2K", never "reason" or
    # "connection refused" (signature tables, __slots__, lookups).
    if not name or not (name[0].isupper() or name[0].isdigit()):
        return False
    # Identifier triples (``("X", "AGENT_BUBBLE", "TOPBAR")``) are data, not items.
    words = [text for text in (name, desc) if text]
    if any("_" in text and " " not in text for text in words):
        return False
    if len(words) == 2 and all(text.isupper() and " " not in text for text in words):
        return False
    for extra in node.elts[3:]:
        value = extra.value if isinstance(extra, ast.Constant) else None
        if isinstance(extra, ast.Constant) and isinstance(value, (int, str)):
            continue
        if isinstance(extra, (ast.Name, ast.Attribute, ast.UnaryOp, ast.Call)):
            continue
        return False
    return True


class _Visitor(ast.NodeVisitor):
    def __init__(self, messages: MessageSet, ref: str):
        self.messages = messages
        self.ref = ref
        self.class_ctxt: list[str | None] = []

    def _add(self, text, kind, ctxt=None):
        if text is not None:
            self.messages.add(text, kind, self.ref, ctxt)

    def _add_all(self, node, kind, ctxt=None):
        for text in _strs(node):
            self.messages.add(text, kind, self.ref, ctxt)

    def visit_ClassDef(self, node: ast.ClassDef):
        attrs = {}
        for stmt in node.body:
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 \
                    and isinstance(stmt.targets[0], ast.Name):
                attrs[stmt.targets[0].id] = stmt.value
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) \
                    and stmt.value is not None:
                attrs[stmt.target.id] = stmt.value
        ctxt = _str(attrs.get("bl_translation_context"))
        for attr, kind in CLASS_ATTRS.items():
            self._add(_str(attrs.get(attr)), kind, ctxt if attr == "bl_label" else None)
        is_bl_type = "bl_idname" in attrs or "bl_label" in attrs
        if is_bl_type and "bl_description" not in attrs:
            doc = ast.get_docstring(node, clean=False)
            if doc:
                self._add(clean_docstring(doc), "tooltip")
        self.class_ctxt.append(ctxt)
        self.generic_visit(node)
        self.class_ctxt.pop()

    def visit_Assign(self, node: ast.Assign):
        if any(isinstance(t, ast.Name) and t.id == "__slots__" for t in node.targets):
            return
        self.generic_visit(node)

    def visit_Tuple(self, node: ast.Tuple):
        if _is_enum_item(node):
            self._add(_str(node.elts[1]), "enum")
            desc = _str(node.elts[2])
            # ("INVERT", "Invert", "MODIFIER"): a trailing identifier is data.
            if not (desc.isupper() and " " not in desc):
                self._add(desc, "tooltip")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        name = _call_name(node)
        keywords = {kw.arg: kw.value for kw in node.keywords if kw.arg}
        if name.endswith("Property"):
            ctxt = _str(keywords.get("translation_context"))
            self._add_all(keywords.get("name"), "property", ctxt)
            self._add_all(keywords.get("description"), "tooltip")
        elif name in MARKERS and node.args:
            ctxt = _str(node.args[1]) if len(node.args) > 1 else _str(keywords.get("msgctxt"))
            self._add_all(node.args[0], MARKERS[name], ctxt)
        elif name == "report" and len(node.args) >= 2:
            self._add_all(node.args[1], "report")
        translate = keywords.get("translate")
        if not (isinstance(translate, ast.Constant) and translate.value is False):
            ctxt = _str(keywords.get("text_ctxt"))
            for key in UI_KEYWORDS:
                if key in keywords:
                    self._add_all(keywords[key], "label", ctxt if key == "text" else None)
        self.generic_visit(node)


def extract_source(source: str, ref: str) -> MessageSet:
    messages = MessageSet()
    tree = ast.parse(source)
    _Visitor(messages, ref).visit(tree)
    return messages


def extract_file(path: Path, ref: str) -> MessageSet:
    return extract_source(path.read_text(encoding="utf-8"), ref)
