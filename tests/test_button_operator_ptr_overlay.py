# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""`button_operator_ptr_ensure()` must never return null: Mixar draw code
writes operator properties through it without a check
(`RNA_boolean_set(button_operator_ptr_ensure(but), "clear", ...)` in the
Director cinema strip), and a button whose Python operator was not registered
yet had no `optype`, so upstream returned null and the 4.4.0 app crashed in
`RNA_boolean_set`. The overlay hands such a button an empty
OperatorProperties pointer, as `WM_operator_properties_create` does for an
unknown operator. The live replay is `tests/qa/cinema_missing_operator_e2e.py`."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "src/source/blender/editors/interface/interface.cc"


def _strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def _ensure_fn(text: str) -> str:
    start = text.index("PointerRNA *button_operator_ptr_ensure(Button *but)")
    return _strip_comments(text[start : text.index("\n}\n", start)])


def test_a_button_without_an_operator_gets_empty_operator_properties():
    text = OVERLAY.read_text(encoding="utf-8")
    fn = _ensure_fn(text)
    # Upstream's single guarded branch left `opptr` null when `optype` was null.
    assert "if (but->optype && !but->opptr)" not in fn
    assert "return nullptr" not in fn
    head, _, missing = fn.partition("else {")
    assert "WM_operator_properties_create_ptr(but->optype)" in head
    assert "RNA_pointer_create_discrete(" in missing and "RNA_OperatorProperties" in missing
    assert "but->opptr = MEM_new<PointerRNA>(" in missing
    assert fn.rstrip().endswith("return but->opptr;")
    assert '#include "RNA_prototypes.hh"' in text



LAYOUT = ROOT / "src/source/blender/editors/interface/interface_layout.cc"
CARD = ROOT / "src/source/blender/editors/interface/interface_mixar_profile_card.cc"


def test_layout_op_with_an_unknown_operator_returns_empty_operator_properties():
    # `Layout::op("MIXAR_OT_open_billing" / "MIXAR_OT_mirror", ...)` returned
    # PointerRNA_NULL before the Python operator registered, and the profile
    # card's RNA_string_set / the UV panel's RNA_enum_set_identifier crashed on
    # its null type (Windows prod). Same contract as button_operator_ptr_ensure().
    text = LAYOUT.read_text(encoding="utf-8")
    start = text.index("#define UI_OPERATOR_ERROR_RET(")
    macro = text[start : text.index("(void)0", start)]
    assert "return PointerRNA_NULL;" not in macro
    assert "return RNA_pointer_create_discrete(nullptr, RNA_OperatorProperties, nullptr);" in macro
    assert "item_disabled(this, _opname);" in macro
    assert '#include "RNA_prototypes.hh"' in text


def test_profile_card_has_no_cta_until_open_billing_registers():
    # Without the guard, op() drew a label reading the raw idname and mark_last
    # painted it as the accent pill ("MIXAR_OT_open_billing", clicks did nothing).
    text = _strip_comments(CARD.read_text(encoding="utf-8"))
    start = text.index("void add_usage(")
    fn = text[start : text.index("\n}\n", start)]
    guard = fn.index('if (WM_operatortype_find("MIXAR_OT_open_billing", true) != nullptr) {')
    body = fn[guard : fn.index("\n  }\n", guard)]
    assert 'cta.op("MIXAR_OT_open_billing"' in body
    assert "mark_last(&cta, MixarCardElement::AccentButton);" in body
    assert fn.count("MixarCardElement::AccentButton") == 1
