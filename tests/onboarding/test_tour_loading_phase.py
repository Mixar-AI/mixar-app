# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The tour waits on a loading card for a pack that is downloading, up to
``PACK_WAIT_S``, then plays localized if the first part landed or English
with subtitles otherwise."""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

if "requests" not in sys.modules:
    sys.modules["requests"] = MagicMock(name="requests")

from mixar.modules.onboarding.core.tour import config, media, pack_fetch, session_lifecycle  # noqa: E402
from mixar.modules.onboarding.core.tour.beats import MIXAR_INTRO  # noqa: E402


class Dummy(session_lifecycle.SessionLifecycleMixin):
    def __init__(self):
        self.tour = MIXAR_INTRO
        self.language = "fr"
        self._loading = True
        self._loading_deadline = 110.0
        self.begun = []
        self.removed = 0

    def _remove_draw_handlers(self):
        self.removed += 1

    def _begin(self, plan):
        self.begun.append(plan.narration)
        return True


def _plan(narration):
    return media.MediaPlan(MIXAR_INTRO, narration, ("x",), None, None)


def test_waits_while_downloading_then_begins_localized(monkeypatch):
    d = Dummy()
    clock = {"t": 100.0}
    monkeypatch.setattr(session_lifecycle.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(pack_fetch, "state", lambda code: {"status": "downloading"})
    plans = iter([_plan("en"), _plan("en"), _plan("fr")])
    monkeypatch.setattr(media, "resolve", lambda tour, lang: next(plans))
    d._tick_loading(); assert d._loading and d.begun == []
    clock["t"] = 105.0
    d._tick_loading(); assert d._loading and d.begun == []
    d._tick_loading()
    assert not d._loading and d.begun == ["fr"] and d.removed == 1


def test_deadline_falls_back_to_english(monkeypatch):
    d = Dummy()
    clock = {"t": 100.0}
    monkeypatch.setattr(session_lifecycle.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(pack_fetch, "state", lambda code: {"status": "downloading"})
    monkeypatch.setattr(media, "resolve", lambda tour, lang: _plan("en"))
    clock["t"] = 109.9
    d._tick_loading(); assert d._loading
    clock["t"] = 110.0
    d._tick_loading()
    assert not d._loading and d.begun == ["en"]


def test_failed_fetch_stops_waiting_at_once(monkeypatch):
    d = Dummy()
    monkeypatch.setattr(session_lifecycle.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(pack_fetch, "state", lambda code: {"status": "failed"})
    monkeypatch.setattr(media, "resolve", lambda tour, lang: _plan("en"))
    d._tick_loading()
    assert not d._loading and d.begun == ["en"]


def test_pack_may_arrive_only_while_a_download_runs(monkeypatch):
    monkeypatch.setattr(pack_fetch, "prefetch", lambda code: True)
    monkeypatch.setattr(pack_fetch, "state", lambda code: {"status": "downloading"})
    assert session_lifecycle.SessionLifecycleMixin._pack_may_arrive("fr")
    monkeypatch.setattr(pack_fetch, "state", lambda code: {"status": "failed"})
    assert not session_lifecycle.SessionLifecycleMixin._pack_may_arrive("fr")


def test_wait_budget_is_ten_seconds():
    assert config.PACK_WAIT_S == 10.0
