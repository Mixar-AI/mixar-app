# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The tour language table, its resolution order and the change hook."""

import pytest

from mixar.modules.onboarding.core.tour import language


def test_order_is_the_product_sequence_with_english_first():
    assert language.CODES == ("en", "zh", "ko", "ja", "ar", "fr", "de", "es", "it", "pt")
    assert language.DEFAULT_CODE == "en"
    assert [lang.english for lang in language.LANGUAGES] == [
        "English", "Mandarin", "Korean", "Japanese", "Arabic",
        "French", "German", "Spanish", "Italian", "Portuguese",
    ]


def test_enum_items_follow_the_table():
    items = language.enum_items()
    assert [i[0] for i in items] == list(language.CODES)
    assert all(len(i) == 3 and i[1] for i in items)


@pytest.mark.parametrize("raw, expected", [
    ("fr", "fr"), (" fr ", "fr"), ("fr_FR", "fr"), ("pt_BR", "pt"), ("zh_HANS", "zh"),
    ("en_GB", "en"), ("de-DE", "de"), ("", "en"), (None, "en"), ("xx", "en"), (42, "en"),
])
def test_normalize_accepts_codes_and_blender_locales(raw, expected):
    assert language.normalize(raw) == expected


def test_only_english_is_bundled():
    assert language.is_bundled("en")
    assert language.is_bundled("en_US")
    assert not any(language.is_bundled(c) for c in language.CODES if c != "en")


def test_resolution_env_beats_stored_beats_default():
    assert language.resolve("ja", "fr") == "ja"
    assert language.resolve("", "fr") == "fr"
    assert language.resolve(None, None) == "en"
    assert language.resolve("bogus", "fr") == "en"   # a bad override still overrides


def test_current_reads_env_then_config(monkeypatch):
    monkeypatch.setattr(language, "stored", lambda: "de")
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
        assert language.set_stored("pt_BR") == "pt"
    finally:
        language.remove_listener(seen.append)
    assert written == {language.CONFIG_KEY: "pt"}
    assert seen == ["pt"]


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
