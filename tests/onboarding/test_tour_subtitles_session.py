# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""When the session shows subtitles: only for a language the narration is
not in (English playing for a French user), or when QA forces them."""

import sys
from unittest.mock import MagicMock

if "requests" not in sys.modules:
    sys.modules["requests"] = MagicMock(name="requests")

from mixar.modules.onboarding.core.tour import config, session_lifecycle, srt  # noqa: E402


def _fake_load(code):
    return srt.Subtitles(code, (srt.Cue(0, 1000, "x"),)) if code == "fr" else None


def test_english_user_gets_no_subtitles(monkeypatch):
    monkeypatch.setattr(srt, "load", _fake_load)
    monkeypatch.delenv(config.ENV_SUBTITLES, raising=False)
    assert session_lifecycle._subtitles_for("en", "en") is None


def test_french_user_over_english_narration_gets_french(monkeypatch):
    monkeypatch.setattr(srt, "load", _fake_load)
    monkeypatch.delenv(config.ENV_SUBTITLES, raising=False)
    subs = session_lifecycle._subtitles_for("fr", "en")
    assert subs is not None and subs.code == "fr"


def test_localized_narration_hides_subtitles(monkeypatch):
    monkeypatch.setattr(srt, "load", _fake_load)
    monkeypatch.delenv(config.ENV_SUBTITLES, raising=False)
    assert session_lifecycle._subtitles_for("fr", "fr") is None


def test_missing_file_is_silently_none(monkeypatch):
    monkeypatch.setattr(srt, "load", _fake_load)
    monkeypatch.delenv(config.ENV_SUBTITLES, raising=False)
    assert session_lifecycle._subtitles_for("zh", "en") is None


def test_qa_can_force_subtitles(monkeypatch):
    monkeypatch.setattr(srt, "load", _fake_load)
    monkeypatch.setenv(config.ENV_SUBTITLES, "always")
    assert session_lifecycle._subtitles_for("fr", "fr") is not None


def test_draw_card_accepts_a_subtitle():
    from mixar.modules.onboarding.core.tour.overlays import card
    layout = card.compute_card_layout("half", "bottom_left", (0, 0, 1600, 900), 1.0)
    # Runs under the gpu/blf mocks; must not raise and must call the band.
    card.draw_card(layout, None, 0.2, False, 1.0, subtitle="Bonjour\nle monde",
                   controls_alpha=1.0)
