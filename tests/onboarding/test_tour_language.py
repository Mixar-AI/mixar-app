# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The tour language table, its resolution order and the change hook."""

import pytest

from mixar.modules.onboarding.core.tour import language


@pytest.fixture(autouse=True)
def isolate_preferences(monkeypatch):
    from mixar.modules.onboarding.core.tour import language_preferences
    monkeypatch.setattr(language_preferences, "apply_interface", lambda code: None)


def test_order_is_the_product_sequence_with_english_first():
    assert language.CODES[:10] == ("en", "zh", "ko", "ja", "ar", "fr", "de", "es", "it", "pt")
    assert language.DEFAULT_CODE == "en"
    assert [lang.english for lang in language.LANGUAGES[:10]] == [
        "English", "Chinese (Simplified)", "Korean", "Japanese", "Arabic",
        "French", "German", "Spanish", "Italian", "Portuguese (Portugal)",
    ]


def test_enum_items_follow_the_table():
    items = language.enum_items()
    assert [i[0] for i in items] == list(language.CODES)
    assert all(len(i) == 3 and i[1] for i in items)


@pytest.mark.parametrize("raw, expected", [
    ("fr", "fr"), (" fr ", "fr"), ("fr_FR", "fr"), ("pt_BR", "pt_BR"), ("zh_HANS", "zh"),
    ("en_GB", "en_GB"), ("de-DE", "de"), ("", "en"), (None, "en"), ("xx", "en"), (42, "en"),
])
def test_normalize_accepts_codes_and_blender_locales(raw, expected):
    assert language.normalize(raw) == expected


def test_only_english_is_bundled():
    assert language.is_bundled("en")
    assert language.is_bundled("en_US")
    assert not any(language.is_bundled(c) for c in language.CODES if c not in ("en", "en_GB"))


def test_resolution_env_beats_stored_beats_default():
    assert language.resolve("ja", "fr") == "ja"
    assert language.resolve("", "fr") == "fr"
    assert language.resolve(None, None) == "en"
    assert language.resolve("bogus", "fr") == "en"   # a bad override still overrides


def test_current_reads_env_then_config(monkeypatch):
    monkeypatch.setattr(language, "selection", lambda: "de")
    monkeypatch.delenv(language.ENV_LANGUAGE, raising=False)
    assert language.current() == "de"
    monkeypatch.setenv(language.ENV_LANGUAGE, "ko")
    assert language.current() == "ko"


def test_set_stored_persists_normalized_and_notifies(monkeypatch):
    written = {}
    monkeypatch.setattr("mixar.config.config.add_config",
                        lambda k, v: written.__setitem__(k, v) or True)
    seen = []
    language.add_listener(seen.append)
    try:
        assert language.set_stored("pt_BR") == "pt_BR"
    finally:
        language.remove_listener(seen.append)
    assert written == {language.CONFIG_KEY: "pt_BR"}
    assert seen == ["pt_BR"]


def test_set_stored_notifies_even_when_the_write_fails(monkeypatch):
    monkeypatch.setattr("mixar.config.config.add_config", lambda k, v: False)
    seen = []
    language.add_listener(seen.append)
    try:
        language.set_stored("it")
    finally:
        language.remove_listener(seen.append)
    assert seen == ["it"]


def test_a_failing_listener_does_not_block_the_others(monkeypatch):
    monkeypatch.setattr("mixar.config.config.add_config", lambda k, v: True)

    def boom(_code):
        raise RuntimeError("listener broke")

    seen = []
    language.add_listener(boom)
    language.add_listener(seen.append)
    try:
        language.set_stored("es")
    finally:
        language.remove_listener(boom)
        language.remove_listener(seen.append)
    assert seen == ["es"]


def test_all_ui_locales_have_distinct_choices():
    from mixar.modules.common.i18n.constants import LANGUAGE_CODES
    assert {item.locale for item in language.LANGUAGES} == {"en_US", *LANGUAGE_CODES}
    assert len(language.CODES) == len(set(language.CODES)) == 50
    for item in language.LANGUAGES:
        assert language.get(item.locale) == item


@pytest.mark.parametrize("code, narration", [
    ("hi_IN", None), ("ru_RU", None), ("sr_RS@latin", None),
    ("zh_HANT", "zh"), ("pt_BR", "pt"), ("en_GB", "en"), ("de_DE", "de"),
])
def test_ui_choice_is_independent_of_pack_availability(code, narration):
    assert language.narration_code(code) == narration


def test_selection_follows_preferences_without_overwriting_config(monkeypatch):
    import bpy
    from types import SimpleNamespace
    monkeypatch.setattr(bpy, "context", SimpleNamespace(
        preferences=SimpleNamespace(view=SimpleNamespace(language="hi_IN"))))
    monkeypatch.setattr(language, "stored", lambda: "fr")
    monkeypatch.delenv(language.ENV_LANGUAGE, raising=False)
    assert language.selection() == language.current() == "hi_IN"
