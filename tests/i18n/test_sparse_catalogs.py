# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Sparse catalogs (en_GB): only text that differs from the source is stored."""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "i18n"))

import derive_catalogs  # noqa: E402
from i18n_common import SPARSE_CATALOGS, load_runtime_package  # noqa: E402

_constants, po = load_runtime_package()

TEMPLATE = r'''msgid ""
msgstr ""

msgid "Color"
msgstr ""

msgid "Bake"
msgstr ""

msgid "Center View"
msgstr ""

msgid "Normalize"
msgstr ""
'''

CATALOG = r'''# header
msgid ""
msgstr ""
"Language: en_GB\n"

msgid "Bake"
msgstr "Bake"

msgid "Center View"
msgstr "Centre the View"

msgid "Gone"
msgstr "Gone Away"
'''


def test_en_gb_is_sparse():
    assert "en_GB" in SPARSE_CATALOGS


def test_derive_sparse_keeps_only_changed_text(tmp_path):
    template = tmp_path / "mixar.pot"
    template.write_text(TEMPLATE, encoding="utf-8")
    target = tmp_path / "en_GB.po"
    target.write_text(CATALOG, encoding="utf-8")

    written, kept = derive_catalogs._derive_sparse(
        po, po.read_po(template), target, lambda e: derive_catalogs.british(e.msgid))

    entries = [e for e in po.read_po(target) if not e.is_header]
    # Template order; the identical "Bake" and the obsolete "Gone" are dropped;
    # the hand-made "Center View" wins over the derived "Centre View".
    assert [(e.msgid, e.msgstr) for e in entries] == [
        ("Color", "Colour"), ("Center View", "Centre the View"), ("Normalize", "Normalise")]
    assert (written, kept) == (2, 1)
    assert po.header_fields(po.read_po(target))["Language"] == "en_GB"
