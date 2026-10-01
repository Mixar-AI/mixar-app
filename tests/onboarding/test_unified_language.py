# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""One language choice, synchronous registration, complete timed fallback."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mixar.modules.onboarding.core.tour import language, language_preferences, media, srt
from mixar.modules.onboarding.core.tour.beats import MIXAR_INTRO
from mixar.modules.onboarding.core.tour.session_lifecycle import SessionLifecycleMixin

ROOT = Path(__file__).resolve().parents[2]


def test_choice_updates_ui_flags_and_refreshes_catalog_immediately(monkeypatch):
    import bpy
    from mixar.modules.common.i18n.core import runtime
    view = SimpleNamespace(language="en_US", use_translate_interface=False,
                           use_translate_tooltips=False, use_translate_reports=False)
    monkeypatch.setattr(bpy, "context", SimpleNamespace(preferences=SimpleNamespace(view=view)))
    refreshed = []
    monkeypatch.setattr(runtime, "_on_language_changed", lambda: refreshed.append(view.language))
    language_preferences.apply_interface("hi_IN")
    assert view.language == "hi_IN"
    assert view.use_translate_interface and view.use_translate_tooltips and view.use_translate_reports
    assert refreshed == ["hi_IN"]


@pytest.mark.parametrize("existing, expected", [("DEFAULT", ["fr"]), ("de_DE", [])])
def test_restore_only_unsaved_preferences(monkeypatch, existing, expected):
    import bpy
    view = SimpleNamespace(language=existing)
    monkeypatch.setattr(bpy, "context", SimpleNamespace(preferences=SimpleNamespace(view=view)))
    monkeypatch.setattr("mixar.config.config.get_config", lambda: {language.CONFIG_KEY: "fr"})
    applied = []
    monkeypatch.setattr(language_preferences, "apply_interface", applied.append)
    language_preferences.restore_unsaved_choice()
    assert applied == expected


def test_registration_is_synchronous_and_idempotent(monkeypatch):
    import bpy
    from mixar.modules.onboarding.ui.properties import language_props
    class WM:
        pass
    created = []
    monkeypatch.setattr(bpy.types, "WindowManager", WM)
    monkeypatch.setattr(bpy.props, "EnumProperty", lambda **kw: created.append(kw) or object())
    language_props.register()
    prop = WM.mixar_tour_language
    language_props.register()
    assert WM.mixar_tour_language is prop
    assert len(created) == 1 and len(created[0]["items"]) == 50
    language_props.unregister()
    language_props.unregister()
    assert not hasattr(WM, "mixar_tour_language")


@pytest.mark.parametrize("code", language.CODES)
def test_every_choice_has_bundled_valid_subtitles(code):
    subs = srt.load(code)
    assert subs and subs.cues, code
    assert all(c.text.strip() and 0 <= c.start_ms < c.end_ms <= 137300 for c in subs.cues)
    assert all(a.end_ms <= b.start_ms for a, b in zip(subs.cues, subs.cues[1:])), code


@pytest.mark.parametrize("code", [c for c in language.CODES if language.narration_code(c) is None])
def test_subtitle_only_languages_use_english_beats_without_network_wait(code, monkeypatch):
    from mixar.modules.onboarding.core.tour import pack_fetch, packs
    def unexpected(*args, **kwargs):
        pytest.fail("A subtitle-only language must not look for or download a video pack")
    monkeypatch.setattr(packs, "cache_root", unexpected)
    monkeypatch.setattr(packs, "installed", unexpected)
    plan = media.resolve(MIXAR_INTRO, code)
    assert plan.narration == "en" and plan.tour is MIXAR_INTRO and plan.parts is None
    assert not pack_fetch.prefetch(code)
    assert not SessionLifecycleMixin._pack_may_arrive(code)


def test_new_tracks_share_english_cues_and_do_not_bridge_interactive_pauses():
    schedule = json.loads((ROOT / "scripts/dev/tour_subtitles/en.json").read_text())
    times = [(start, end) for start, end, _text in schedule]
    source_codes = [p.stem for p in (ROOT / "scripts/dev/tour_subtitles").glob("*.txt")]
    for code in ["en", "sr_RS@latin", *source_codes]:
        subs = srt.load(code)
        assert [(c.start_ms, c.end_ms) for c in subs.cues] == times, code
        for beat in MIXAR_INTRO.beats:
            if beat.gate:
                assert subs.text_at(beat.clip_end_ms) == "", (code, beat.id)
        assert subs.text_at(130239) and not subs.text_at(130240)


def test_visual_rtl_wrap_starts_at_right_edge():
    # Hebrew is stored in visual order for BLF, so its sentence starts at
    # the right. Rows must be taken from that end too.
    assert srt.wrap("םלוע םולש", 5, len) == ["םולש", "םלוע"]


def test_rtl_assets_are_shaped_but_translator_sources_are_logical():
    for code in ("ar", "fa_IR", "ur"):
        text = " ".join(c.text for c in srt.load(code).cues)
        assert any("\ufb50" <= ch <= "\ufdff" or "\ufe70" <= ch <= "\ufeff" for ch in text)
