# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""PO reading/writing and locale -> catalog resolution (modules/common/i18n)."""

import pytest

from mixar.modules.common.i18n.constants import LANGUAGE_CODES, OPERATOR_CONTEXT
from mixar.modules.common.i18n.core import po
from mixar.modules.common.i18n.core.catalog import (
    build_translation_dict,
    explode_locale,
    load_locale,
    resolve_catalog_code,
)

SAMPLE = r'''# header comment
msgid ""
msgstr ""
"Language: fr_FR\n"

msgid "Bake"
msgstr "Précalculer"

#. label
#: src/a.py
msgctxt "Operator"
msgid "Add Layer"
msgstr "Ajouter un calque"

#, fuzzy
msgid "Doubtful"
msgstr "Douteux"

msgid "Untranslated"
msgstr ""

msgid ""
"Two\n"
"lines \"quoted\""
msgstr "Deux\nlignes « citées »"

#~ msgid "Gone"
#~ msgstr "Parti"
'''


def test_load_messages_keeps_only_usable_translations(tmp_path):
    path = tmp_path / "fr_FR.po"
    path.write_text(SAMPLE, encoding="utf-8")
    assert po.load_messages(path) == {
        (None, "Bake"): "Précalculer",
        ("Operator", "Add Layer"): "Ajouter un calque",
        (None, 'Two\nlines "quoted"'): "Deux\nlignes « citées »",
    }


def test_parse_and_format_round_trip():
    entries = po.parse_po(SAMPLE)
    header = entries[0]
    assert header.is_header
    assert po.header_fields(entries) == {"Language": "fr_FR"}
    by_id = {e.msgid: e for e in entries}
    assert by_id["Add Layer"].msgctxt == "Operator"
    assert by_id["Add Layer"].extracted == ["label"]
    assert by_id["Add Layer"].references == ["src/a.py"]
    assert by_id["Doubtful"].fuzzy
    assert by_id["Gone"].obsolete
    again = po.parse_po(po.format_po(entries))
    assert [(e.key, e.msgstr, e.fuzzy, e.obsolete) for e in again] == \
        [(e.key, e.msgstr, e.fuzzy, e.obsolete) for e in entries]


@pytest.mark.parametrize("locale,expected", [
    ("sr_RS@latin", ["sr_RS@latin", "sr_RS", "sr@latin", "sr"]),
    ("de_DE.UTF-8", ["de_DE", "de"]),
    ("ja", ["ja"]),
    ("", []),
])
def test_explode_locale(locale, expected):
    assert explode_locale(locale) == expected


@pytest.mark.parametrize("locale,expected", [
    ("fr_FR", "fr_FR"), ("fr", "fr_FR"), ("de_AT", "de_DE"), ("zh_CN", "zh_HANS"),
    ("zh_TW", "zh_HANT"), ("pt", "pt_PT"), ("pt_BR", "pt_BR"), ("sr_RS@latin", "sr_RS@latin"),
    ("sr", "sr_RS"), ("es_MX", "es"), ("en_GB", "en_GB"), ("en_US", None), ("en_AU", None),
    ("C", None), ("", None),
])
def test_resolve_catalog_code(locale, expected):
    assert resolve_catalog_code(locale) == expected


def test_every_blender_language_is_listed_once():
    assert len(LANGUAGE_CODES) == 49 == len(set(LANGUAGE_CODES))
    assert "en_US" not in LANGUAGE_CODES


def test_default_context_is_mirrored_to_operator_context():
    out = build_translation_dict({
        (None, "Generate"): "Générer",
        ("Operator", "Bake"): "Précalculer (op)",
        (None, "Bake"): "Précalculer",
        ("Mesh", "Face"): "Face (maillage)",
    })
    assert out[("*", "Generate")] == out[(OPERATOR_CONTEXT, "Generate")] == "Générer"
    assert out[("*", "Bake")] == "Précalculer"
    assert out[(OPERATOR_CONTEXT, "Bake")] == "Précalculer (op)"
    assert out[("Mesh", "Face")] == "Face (maillage)"
    assert ("*", "Face") not in out


def test_load_locale_reads_the_resolved_catalog(tmp_path):
    (tmp_path / "fr_FR.po").write_text(SAMPLE, encoding="utf-8")
    code, messages = load_locale("fr_CA", tmp_path)
    assert code == "fr_FR"
    assert messages[("*", "Bake")] == "Précalculer"
    assert load_locale("de_DE", tmp_path) == (None, {})
    assert load_locale("en_US", tmp_path) == (None, {})
