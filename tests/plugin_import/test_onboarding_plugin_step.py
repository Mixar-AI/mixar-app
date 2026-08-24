# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The onboarding plugin-import step: graph wiring and card copy.

``bpy`` is a MagicMock under this suite, so these pin the declarative
parts — the step graph, the branch targets, and the copy builders —
rather than the GPU draw path.
"""

from __future__ import annotations

import pytest

from mixar.modules.onboarding.constants import (
    STEP_COMPLETION,
    STEP_DONE,
    STEP_INFO_ENGINE_MODE,
    STEP_INFO_MOODBOARD,
    STEP_PLUGIN_IMPORT,
    STEP_PLUGIN_IMPORT_DONE,
    STEP_PLUGIN_IMPORT_NONE,
    TOTAL_INFO_STEPS,
)
from mixar.modules.onboarding.core import plugin_import_bridge as bridge
from mixar.modules.onboarding.core import steps
from mixar.modules.onboarding.core.steps import ACTION_IMPORT_PLUGINS, get_step


@pytest.fixture(autouse=True)
def _clean_bridge():
    bridge.reset()
    yield
    bridge.reset()


class TestStepGraph:
    def test_plugin_import_is_second_to_last(self):
        """Engine Mode → Plugin Import → Completion → Done."""
        assert get_step(STEP_INFO_ENGINE_MODE).continue_step == STEP_PLUGIN_IMPORT
        assert get_step(STEP_PLUGIN_IMPORT).continue_step == STEP_COMPLETION
        assert get_step(STEP_COMPLETION).continue_step == STEP_DONE

    def test_back_chain_is_symmetric(self):
        assert get_step(STEP_PLUGIN_IMPORT).back_step == STEP_INFO_ENGINE_MODE
        assert get_step(STEP_COMPLETION).back_step == STEP_PLUGIN_IMPORT

    def test_declining_goes_straight_to_completion(self):
        step = get_step(STEP_PLUGIN_IMPORT)
        assert step.alt_label
        assert step.alt_step == STEP_COMPLETION

    def test_primary_runs_the_import_action(self):
        assert get_step(STEP_PLUGIN_IMPORT).primary_action == ACTION_IMPORT_PLUGINS

    def test_both_outcome_cards_rejoin_the_flow(self):
        for step_id in (STEP_PLUGIN_IMPORT_NONE, STEP_PLUGIN_IMPORT_DONE):
            assert get_step(step_id).continue_step == STEP_COMPLETION

    def test_outcome_cards_have_no_back_link(self):
        """Neither outcome has a coherent card to step back to: the
        result card would re-offer an import that already ran, and the
        'none found' card is only reachable when the availability gate
        has just disagreed with itself."""
        assert get_step(STEP_PLUGIN_IMPORT_DONE).back_step == ""
        assert get_step(STEP_PLUGIN_IMPORT_NONE).back_step == ""

    def test_progress_badge_counts_the_new_step(self):
        assert TOTAL_INFO_STEPS == 7
        assert get_step(STEP_PLUGIN_IMPORT).progress == (7, TOTAL_INFO_STEPS)

    def test_outcome_cards_are_not_numbered_steps(self):
        for step_id in (STEP_PLUGIN_IMPORT_NONE, STEP_PLUGIN_IMPORT_DONE):
            assert get_step(step_id).progress == (0, 0)


class TestAvailabilityGate:
    """The offer card only appears when there is something to import."""

    def _force(self, monkeypatch, found):
        scan = bridge.ScanResult(version="5.0", count=3) if found else bridge.ScanResult()
        monkeypatch.setattr(bridge, "scan", lambda *a, **k: scan)

    def test_step_is_available_when_plugins_exist(self, monkeypatch):
        self._force(monkeypatch, True)
        assert steps.is_available(STEP_PLUGIN_IMPORT)

    def test_step_is_unavailable_when_nothing_to_import(self, monkeypatch):
        self._force(monkeypatch, False)
        assert not steps.is_available(STEP_PLUGIN_IMPORT)

    def test_steps_without_a_predicate_are_always_available(self):
        assert steps.is_available(STEP_INFO_ENGINE_MODE)
        assert steps.is_available(STEP_COMPLETION)

    def test_forward_walk_skips_the_hidden_card(self, monkeypatch):
        self._force(monkeypatch, False)
        from mixar.modules.onboarding.core import state

        landed = state._resolve_available(STEP_PLUGIN_IMPORT, forward=True)
        assert landed == STEP_COMPLETION

    def test_backward_walk_skips_the_hidden_card(self, monkeypatch):
        """Back from Completion must not land on a card that isn't shown."""
        self._force(monkeypatch, False)
        from mixar.modules.onboarding.core import state

        landed = state._resolve_available(STEP_PLUGIN_IMPORT, forward=False)
        assert landed == STEP_INFO_ENGINE_MODE

    def test_walk_is_a_no_op_when_the_card_is_shown(self, monkeypatch):
        self._force(monkeypatch, True)
        from mixar.modules.onboarding.core import state

        for direction in (True, False):
            assert state._resolve_available(
                STEP_PLUGIN_IMPORT, forward=direction,
            ) == STEP_PLUGIN_IMPORT

    def test_predicate_raising_hides_the_step(self, monkeypatch):
        def _boom():
            raise RuntimeError("scan blew up")

        monkeypatch.setattr(bridge, "scan", _boom)
        assert not steps.is_available(STEP_PLUGIN_IMPORT)


class TestAnsweredOfferIsNotReOffered:
    """Back from Completion must not walk into an import that already ran.

    ``_resolve_available`` runs the predicate in BOTH directions, so the
    gate — not ``back_step`` — is what has to know the offer was answered.
    Declining is deliberately NOT "answered": that user may reconsider.
    """

    @pytest.fixture(autouse=True)
    def _plugins_exist(self, monkeypatch):
        monkeypatch.setattr(
            bridge, "scan", lambda refresh=False: bridge.ScanResult("4.5", 3)
        )

    def test_offer_is_shown_before_the_import(self):
        assert steps.is_available(STEP_PLUGIN_IMPORT) is True

    def test_offer_is_gone_once_the_import_has_run(self, monkeypatch):
        monkeypatch.setattr(bridge, "import_ran", lambda: True)
        assert steps.is_available(STEP_PLUGIN_IMPORT) is False

    def test_back_from_completion_skips_the_answered_offer(self, monkeypatch):
        from mixar.modules.onboarding.core.state import _resolve_available

        monkeypatch.setattr(bridge, "import_ran", lambda: True)
        landing = _resolve_available(
            get_step(STEP_COMPLETION).back_step, forward=False
        )
        assert landing == STEP_INFO_ENGINE_MODE

    def test_back_from_completion_still_reaches_a_declined_offer(self):
        from mixar.modules.onboarding.core.state import _resolve_available

        landing = _resolve_available(
            get_step(STEP_COMPLETION).back_step, forward=False
        )
        assert landing == STEP_PLUGIN_IMPORT

    def test_declining_does_not_mark_the_offer_answered(self):
        assert bridge.import_ran() is False

    def test_a_completed_import_marks_it_answered(self, monkeypatch):
        monkeypatch.setattr(
            bridge, "import_everything", bridge.import_everything
        )
        monkeypatch.setattr(
            "mixar.modules.plugin_import.core.source_select.select_source",
            lambda: None,
        )
        bridge.import_everything()
        assert bridge.import_ran() is True


class TestProgressDots:
    def _force(self, monkeypatch, found):
        scan = bridge.ScanResult(version="5.0", count=3) if found else bridge.ScanResult()
        monkeypatch.setattr(bridge, "scan", lambda *a, **k: scan)

    def test_seven_steps_when_the_card_shows(self, monkeypatch):
        self._force(monkeypatch, True)
        assert steps.numbered_progress(STEP_PLUGIN_IMPORT) == (7, 7)
        assert steps.numbered_progress(STEP_INFO_ENGINE_MODE) == (6, 7)

    def test_six_steps_when_the_card_is_skipped(self, monkeypatch):
        """No stale 'OF 7' badge on a tour that only shows six cards."""
        self._force(monkeypatch, False)
        assert steps.numbered_progress(STEP_INFO_ENGINE_MODE) == (6, 6)
        assert steps.numbered_progress(STEP_PLUGIN_IMPORT) == (0, 0)

    def test_every_numbered_step_is_reachable_and_ordered(self, monkeypatch):
        self._force(monkeypatch, True)
        chain = steps._numbered_chain()
        assert chain[0] == STEP_INFO_MOODBOARD
        assert chain[-1] == STEP_PLUGIN_IMPORT
        assert len(chain) == len(set(chain))       # no repeats → no cycle
        positions = [steps.numbered_progress(s)[0] for s in chain]
        assert positions == list(range(1, len(chain) + 1))


class TestOfferCardCopy:
    def _body(self, monkeypatch, scan):
        from mixar.modules.onboarding.ui.operators import card_config

        monkeypatch.setattr(bridge, "scan", lambda *a, **k: scan)
        return card_config._plugin_import_body()

    def test_names_the_count_and_version_when_found(self, monkeypatch):
        body = self._body(monkeypatch, bridge.ScanResult(version="5.0", count=7))
        assert "7 plugins" in body[0]
        assert "5.0" in body[0]

    def test_singular_plugin_reads_naturally(self, monkeypatch):
        body = self._body(monkeypatch, bridge.ScanResult(version="4.2", count=1))
        assert "1 plugin " in body[0] or body[0].count("1 plugin") == 1
        assert "1 plugins" not in body[0]

    def test_claims_no_count_when_nothing_found(self, monkeypatch):
        body = self._body(monkeypatch, bridge.ScanResult())
        joined = " ".join(body)
        assert "found" not in joined.lower()
        assert "0" not in joined


class TestResultCardCopy:
    def _body(self, monkeypatch, result):
        from mixar.modules.onboarding.ui.operators import card_config

        monkeypatch.setattr(bridge, "last_import_result", lambda: result)
        return card_config._import_done_body()

    def test_reports_counts(self, monkeypatch):
        body = self._body(
            monkeypatch, bridge.ImportResult(imported=7, enabled=6)
        )
        assert "7" in body[0] and "6" in body[0]

    def test_reports_failures_honestly(self, monkeypatch):
        body = self._body(
            monkeypatch,
            bridge.ImportResult(imported=5, enabled=3, enable_failed=2),
        )
        joined = " ".join(body)
        assert "2" in joined
        assert "couldn't" in joined.lower()

    def test_says_nothing_to_do_when_all_present(self, monkeypatch):
        body = self._body(
            monkeypatch, bridge.ImportResult(already_present=4)
        )
        assert "already" in body[0].lower()

    def test_always_points_at_preferences(self, monkeypatch):
        body = self._body(monkeypatch, bridge.ImportResult(imported=1, enabled=1))
        assert "Preferences" in body[-1]


class TestBridgeFailsSoft:
    def test_scan_returns_empty_when_plugin_import_explodes(self, monkeypatch):
        import mixar.modules.plugin_import.core.source_select as ss

        def _boom():
            raise RuntimeError("disk on fire")

        monkeypatch.setattr(ss, "select_source", _boom)
        result = bridge.scan(refresh=True)
        assert not result.found          # degraded, but the tour survives
        assert result.count == 0

    def test_scan_is_cached_until_refreshed(self, monkeypatch):
        calls = []

        import mixar.modules.plugin_import.core.source_select as ss

        def _counted():
            calls.append(1)
            return None

        monkeypatch.setattr(ss, "select_source", _counted)
        bridge.scan(refresh=True)
        bridge.scan()
        bridge.scan()
        assert len(calls) == 1

        bridge.scan(refresh=True)
        assert len(calls) == 2
