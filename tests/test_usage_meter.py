# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the account card's credit usage figures.

Covers the pure state/threshold logic, the greeting-name derivation, and
the cross-language contracts that can't be exercised through mocked
``bpy``: the C++ card reading exactly the RNA properties Python writes,
and the two colour thresholds agreeing across the two languages.
"""

import ast
import inspect
from pathlib import Path

import pytest

from mixar.modules.common.usage import constants
from mixar.modules.common.usage.core import account, state

REPO_ROOT = Path(__file__).resolve().parents[1]
TOPBAR_PY = (
    REPO_ROOT
    / "src/scripts/mixar/modules/space_mixie_chat/ui/topbar.py"
)
CARD_CC = (
    REPO_ROOT
    / "src/source/blender/editors/interface/interface_mixar_profile_card.cc"
)
CARD_DRAW_CC = (
    REPO_ROOT
    / "src/source/blender/editors/interface/interface_mixar_profile_card_draw.cc"
)
USAGE_PROPS_PY = (
    REPO_ROOT
    / "src/scripts/mixar/modules/common/usage/ui/properties/usage_props.py"
)
CARD_BUTTON_CC = (
    REPO_ROOT
    / "src/source/blender/editors/interface/interface_mixar_card_button.cc"
)
CARD_PAINT_HH = (
    REPO_ROOT
    / "src/source/blender/editors/interface/interface_mixar_card_paint.hh"
)
CARD_HH = (
    REPO_ROOT
    / "src/source/blender/editors/interface/interface_mixar_profile_card.hh"
)


def _payload(**overrides):
    """A `/subscriptions/status` success envelope with sane defaults."""
    data = {
        "plan_slug": "pro",
        "plan_name": "Pro",
        "billing_interval": "monthly",
        "credits_per_month": 10000,
        "balance_cents": 6800,
        "plan_value_cents": 10000,
        "usage_pct": 32.0,
        "cycle_start": "2026-08-01T00:00:00+00:00",
        "cycle_end": "2026-08-31T00:00:00+00:00",
        "days_left": 18,
        "subscription_expires_at": None,
    }
    data.update(overrides)
    return {"status": "success", "data": data}


@pytest.fixture(autouse=True)
def _reset_state():
    state.clear()
    yield
    state.clear()


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


class TestSnapshotFromPayload:
    def test_parses_full_envelope(self):
        snap = state.snapshot_from_payload(_payload())
        assert snap.has_subscription
        assert snap.plan_name == "Pro"
        assert snap.usage_pct == 32.0
        assert snap.credits_remaining == 6800
        assert snap.credits_total == 10000
        assert snap.days_left == 18

    def test_accepts_bare_inner_dict(self):
        """The HTTP client has handed back both shapes; neither may break."""
        inner = _payload()["data"]
        assert state.snapshot_from_payload(inner).credits_total == 10000

    def test_remaining_is_complement_of_backend_usage_pct(self):
        """The server's usage_pct is authoritative — never recomputed from
        the balance, which would drift from the web dashboard on
        grandfathered allocations."""
        snap = state.snapshot_from_payload(
            _payload(usage_pct=32.0, balance_cents=1, credits_per_month=10000)
        )
        assert snap.remaining_pct == pytest.approx(68.0)

    def test_usage_pct_is_clamped(self):
        assert state.snapshot_from_payload(_payload(usage_pct=140.0)).remaining_pct == 0.0
        assert state.snapshot_from_payload(_payload(usage_pct=-5.0)).remaining_pct == 100.0

    def test_balance_above_allocation_reads_as_full(self):
        """Top-ups and shared team pools carry a balance past the cycle
        allocation. The backend clamps usage_pct to 0 for that, which is
        the correct reading — none of the allowance is spent — so the
        card must show 100% and a full bar, not an over-full one."""
        snap = state.snapshot_from_payload(
            _payload(credits_per_month=5500, balance_cents=424285, usage_pct=0.0)
        )
        assert snap.remaining_pct == 100.0
        assert state.usage_factor(snap) == 1.0
        assert state.format_remaining_label(snap) == "100% left"
        # Both figures stay visible; the ratio is not "corrected" away.
        assert snap.credits_remaining == 424285
        assert snap.credits_total == 5500

    def test_credits_remaining_override_wins(self):
        snap = state.snapshot_from_payload(_payload(), credits_remaining=1234)
        assert snap.credits_remaining == 1234

    def test_garbage_values_do_not_raise(self):
        snap = state.snapshot_from_payload(
            _payload(credits_per_month="lots", usage_pct=None, days_left="x")
        )
        assert snap.credits_total == 0
        assert snap.usage_pct == 0.0
        assert snap.days_left == 0

    def test_non_dict_payload_is_an_error_snapshot(self):
        snap = state.snapshot_from_payload("<html>502</html>")
        assert snap.error
        assert not snap.has_subscription


# ---------------------------------------------------------------------------
# Free tier / errors
# ---------------------------------------------------------------------------


class TestFreeTierAndErrors:
    def test_free_tier_has_no_subscription(self):
        """A 404 from /subscriptions/status is a normal account state."""
        snap = state.snapshot_free_tier(credits_remaining=250)
        assert not snap.has_subscription
        assert snap.credits_remaining == 250
        assert not snap.error

    def test_free_tier_shows_no_percentage(self):
        snap = state.snapshot_free_tier()
        assert state.format_remaining_label(snap) == "Upgrade"
        assert state.usage_factor(snap) == 0.0

    def test_error_snapshot_keeps_previous_figures(self):
        state.set_snapshot(state.snapshot_from_payload(_payload()))
        snap = state.snapshot_error("Connection refused")
        assert snap.error == "Connection refused"
        assert snap.credits_remaining == 6800
        assert snap.plan_name == "Pro"
        assert snap.has_subscription

    def test_error_snapshot_is_timestamped_so_retries_stay_on_ttl(self):
        """A hard-down backend must be retried on the TTL cadence, not on
        every tick."""
        snap = state.snapshot_error("boom", now=500.0)
        state.set_snapshot(snap)
        assert not state.is_stale(now=500.0 + constants.USAGE_TTL_SECONDS - 1)
        assert state.is_stale(now=500.0 + constants.USAGE_TTL_SECONDS + 1)

    def test_empty_cache_is_stale(self):
        assert state.is_stale()

    def test_clear_resets_to_empty(self):
        state.set_snapshot(state.snapshot_from_payload(_payload()))
        state.clear()
        assert state.get_snapshot() is state.EMPTY


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------


class TestSeverity:
    @pytest.mark.parametrize(
        "remaining_pct,expected",
        [
            (100.0, constants.SEVERITY_OK),
            (50.0, constants.SEVERITY_OK),
            (49.9, constants.SEVERITY_WARNING),
            (20.0, constants.SEVERITY_WARNING),
            (19.9, constants.SEVERITY_CRITICAL),
            (0.0, constants.SEVERITY_CRITICAL),
        ],
    )
    def test_bands(self, remaining_pct, expected):
        assert state.usage_severity(remaining_pct) == expected

    def test_thresholds_match_the_cpp_card(self):
        """The bar is coloured in C++ and the wording chosen in Python; a
        drifted boundary would show an amber bar beside a green label."""
        draw = CARD_DRAW_CC.read_text(encoding="utf-8")
        assert (
            "constexpr float CARD_USAGE_CRITICAL_FACTOR = %.2ff"
            % (constants.USAGE_CRITICAL_PCT / 100.0)
            in draw
        )
        assert (
            "constexpr float CARD_USAGE_WARNING_FACTOR = %.2ff"
            % (constants.USAGE_WARNING_PCT / 100.0)
            in draw
        )


# ---------------------------------------------------------------------------
# Top-up eligibility
# ---------------------------------------------------------------------------


class TestCanTopUp:
    def test_plain_subscriber_can(self):
        assert state.snapshot_from_payload(_payload()).can_top_up

    def test_trial_cannot(self):
        """Mirrors the server rule behind /subscriptions/credit-topup."""
        snap = state.snapshot_from_payload(_payload(plan_slug="trial-7d"))
        assert snap.is_trial
        assert not snap.can_top_up

    def test_cancelling_cannot(self):
        snap = state.snapshot_from_payload(
            _payload(subscription_expires_at="2026-09-01T00:00:00+00:00")
        )
        assert snap.is_cancelling
        assert not snap.can_top_up

    def test_free_tier_cannot(self):
        assert not state.snapshot_free_tier().can_top_up


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


class TestFormatting:
    def test_label_reads_as_remaining(self):
        snap = state.snapshot_from_payload(_payload(usage_pct=32.0))
        assert state.format_remaining_label(snap) == "68% left"

    def test_label_floors_rather_than_rounds_up(self):
        """0.4% left must not reassure the user with '1% left'."""
        snap = state.snapshot_from_payload(_payload(usage_pct=99.6))
        assert state.format_remaining_label(snap) == "0% left"

    def test_factor_is_the_remaining_portion(self):
        snap = state.snapshot_from_payload(_payload(usage_pct=25.0))
        assert state.usage_factor(snap) == pytest.approx(0.75)

    def test_cycle_label_counts_down_to_renewal(self):
        snap = state.snapshot_from_payload(_payload(days_left=18))
        assert state.format_cycle_label(snap) == "Pro · 18 days left in cycle"

    def test_cycle_label_says_expires_when_cancelling(self):
        snap = state.snapshot_from_payload(
            _payload(days_left=3, subscription_expires_at="2026-09-01T00:00:00+00:00")
        )
        assert state.format_cycle_label(snap) == "Pro · Expires in 3 days"

    def test_cycle_label_singular_day(self):
        snap = state.snapshot_from_payload(_payload(days_left=1))
        assert state.format_cycle_label(snap) == "Pro · 1 day left in cycle"

    def test_credits_are_thousands_separated(self):
        assert state.format_credits(6800) == "6,800"

    def test_snapshot_dict_is_display_ready(self):
        state.set_snapshot(state.snapshot_from_payload(_payload(usage_pct=90.0)))
        info = state.build_snapshot_dict()
        assert info["label"] == "10% left"
        assert info["severity"] == constants.SEVERITY_CRITICAL
        assert info["factor"] == pytest.approx(0.10)
        assert info["can_top_up"] is True


# ---------------------------------------------------------------------------
# Top-bar wiring (source-level: bpy is a MagicMock in this suite)
# ---------------------------------------------------------------------------


class TestProfileCardWiring:
    @staticmethod
    def _profile_panel_source():
        source = TOPBAR_PY.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "MIXAR_PT_profile":
                return ast.get_source_segment(source, node)
        raise AssertionError("MIXAR_PT_profile not found")

    def test_dropdown_draws_the_native_card(self):
        assert "layout.mixar_profile_card()" in self._profile_panel_source()

    def test_dropdown_falls_back_when_card_missing(self):
        """A build whose C++ predates the card item must still reach the
        account actions rather than showing an empty popover."""
        src = self._profile_panel_source()
        assert "except AttributeError" in src
        assert "_draw_fallback_menu" in src
        assert "mixie_chat.logout" in src

    def test_draw_path_never_fetches(self):
        """A popover can redraw on every mouse move; a network call or a
        refresh request in draw would hammer the API."""
        src = self._profile_panel_source()
        for forbidden in ("request_refresh", "get_status", "requests.", "_start_fetch"):
            assert forbidden not in src, forbidden


class TestCardRnaContract:
    """The card is drawn in C++ and cannot read the Python cache, so the
    WindowManager mirror is the whole interface between them."""

    @staticmethod
    def _mirrored_property_names():
        from mixar.modules.common.usage.ui.properties import usage_props

        return set(usage_props._PROP_NAMES)

    def test_every_mirrored_property_is_read_by_the_card(self):
        card = CARD_CC.read_text(encoding="utf-8")
        for name in self._mirrored_property_names():
            assert '"%s"' % name in card, name

    def test_every_property_the_card_reads_is_mirrored(self):
        """A typo'd name in C++ reads as a missing property and silently
        draws zeros, so pin the direction that has no runtime signal."""
        import re

        card = CARD_CC.read_text(encoding="utf-8")
        referenced = set(re.findall(r'"(mixar_(?:usage|account)_\w+)"', card))
        assert referenced, "card reads no usage properties"
        assert referenced <= self._mirrored_property_names()

    def test_poller_writes_every_mirrored_property(self):
        from mixar.modules.common.usage.core import poller

        src = inspect.getsource(poller._mirror_to_rna)
        for name in self._mirrored_property_names():
            if name == "mixar_account_name":
                continue  # Owned by the login path, not the billing poll.
            assert name in src, name

    def test_properties_live_on_window_manager_not_scene(self):
        """Plan and credit balance must never be serialized into a .blend
        and handed to whoever opens the file."""
        source = USAGE_PROPS_PY.read_text(encoding="utf-8")
        assert "bpy.types.Scene" not in source
        assert "bpy.types.WindowManager" in source


class TestCardColourLiterals:
    """A `uchar[4]` colour written with three components zero-fills alpha
    and draws completely invisible — which is exactly how the usage bar's
    fill silently disappeared. Cheap to pin, near-impossible to spot in
    review."""

    COLOUR_FILES = tuple(
        REPO_ROOT / "src/source/blender/editors/interface" / name
        for name in (
            "interface_mixar_palette.hh",
            "interface_mixar_card_paint.hh",
            "interface_mixar_card_icons.cc",
            "interface_mixar_card_button.cc",
            "interface_mixar_profile_card.cc",
            "interface_mixar_profile_card_draw.cc",
        )
    )

    @staticmethod
    def _rgba_literals(source):
        import re

        # `... uchar NAME[4] = {a, b, c, d};` — 2D arrays such as
        # MX_GRADIENT[4][4] don't match and carry their own rows.
        return re.findall(
            r"uchar\s+(\w+)\s*\[4\]\s*=\s*\{([^}]*)\}", source
        )

    def test_every_rgba_literal_specifies_alpha(self):
        seen = 0
        for path in self.COLOUR_FILES:
            source = path.read_text(encoding="utf-8")
            for name, body in self._rgba_literals(source):
                components = [part for part in body.split(",") if part.strip()]
                assert len(components) == 4, (
                    "%s in %s has %d components; a uchar[4] colour must state "
                    "alpha explicitly or it draws invisible"
                    % (name, path.name, len(components))
                )
                seen += 1
        assert seen, "no RGBA literals found — did the files move?"

    def test_usage_bar_ramp_is_opaque(self):
        source = CARD_DRAW_CC.read_text(encoding="utf-8")
        ramp = dict(self._rgba_literals(source))
        for name in ("CARD_USAGE_RAMP_START", "CARD_USAGE_RAMP_END"):
            assert name in ramp, name
            alpha = ramp[name].split(",")[3].strip()
            assert alpha == "255", "%s alpha is %r" % (name, alpha)


class TestCardGlyphs:
    """The card draws its own thin-stroke glyphs. Blender's stock ICON_*
    set is weighted for toolbars and out-shouts the labels at card
    scale, so a stray ICON_ constant creeping back in is a regression."""

    def test_card_requests_no_stock_glyphs(self):
        import re

        source = CARD_CC.read_text(encoding="utf-8")
        used = set(re.findall(r"\bICON_[A-Z0-9_]+\b", source))
        assert used <= {"ICON_NONE"}, sorted(used - {"ICON_NONE"})

    def test_every_button_kind_names_a_glyph(self):
        """A button built without an icon silently centres its label,
        which is only correct for the two kinds that want it."""
        source = CARD_CC.read_text(encoding="utf-8")
        for glyph in ("Grid", "Sliders", "Document", "Alert", "Cross"):
            assert "MixarCardIcon::%s" % glyph in source, glyph


class TestCardSizingContract:
    """The card suppresses the stock text pass and paints with its own
    font scale and padding, but `uiLayout` still sizes every button from
    the default widget font. Anything the painter spends beyond that
    estimate is clipped by `fontstyle_draw` with no ellipsis — the
    failure mode is a label quietly reading "Log" instead of "Logout",
    which no runtime signal reports."""

    def test_button_chrome_is_declared_once(self):
        """The builder measures what the painter spends, so the two must
        read the same numbers rather than each hardcoding them."""
        header = CARD_PAINT_HH.read_text(encoding="utf-8")
        for name in (
            "MIXAR_CARD_BUTTON_INSET",
            "MIXAR_CARD_BUTTON_PAD",
            "MIXAR_CARD_BUTTON_ICON",
            "MIXAR_CARD_BUTTON_ICON_GAP",
        ):
            assert name in header, name

        button = CARD_BUTTON_CC.read_text(encoding="utf-8")
        for name in ("MIXAR_CARD_BUTTON_INSET", "MIXAR_CARD_BUTTON_PAD"):
            assert name in button, name

    def test_collapsing_rows_declare_the_width_they_need(self):
        """A row set to Left/Center alignment shrinks to the layout's
        estimate of its label alone; without a measured width the
        painter's chrome comes off the end of the string."""
        source = CARD_CC.read_text(encoding="utf-8")
        assert "card_units_for_text" in source
        assert "mixar_card_button_chrome" in source
        # The CTA is the one collapsing row left in the card.
        assert "cta.ui_units_x_set" in source

    def test_logout_strip_is_full_width(self):
        """Centring the logout row is what clipped "Logout" to "Log" —
        the painter centres the contents, the row must not also collapse."""
        source = CARD_CC.read_text(encoding="utf-8")
        tree_start = source.index("void add_logout(")
        body = source[tree_start:source.index("\n}", tree_start)]
        assert "LayoutAlign::Center" not in body

    def test_button_heights_use_scale_not_units(self):
        """`ui_units_y_set` forces the enclosing *layout item's* height
        while `ui_item_size` still reports each button's own rect, created
        one unit tall — the row grows, the button stays ~20px, and the
        fixed 8px `MX_R_MD` radius lands at 0.4 of that height, drawing
        every action as a lozenge. Only `scale_y` reaches the button, via
        `ui_item_scale`."""
        import re

        source = CARD_CC.read_text(encoding="utf-8")
        assert not re.search(r"\.ui_units_y_set\(", source), (
            "card row heights must go through scale_y_set; ui_units_y_set "
            "pads the row without resizing the button inside it"
        )
        assert re.search(r"\.scale_y_set\(ROW_ACTION\)", source)

    def test_element_range_check_uses_the_sentinel(self):
        """`UI_mixar_card_element_get` range-checks the tag it reads back.
        Bounding on a real kind means the next kind appended to the enum
        reads as None and draws as a blank row."""
        header = CARD_HH.read_text(encoding="utf-8")
        kinds = header[header.index("enum class MixarCardElement"):]
        kinds = kinds[: kinds.index("};")]
        assert kinds.rstrip().rstrip(",").endswith("Count"), (
            "Count must stay last in MixarCardElement"
        )

        source = CARD_CC.read_text(encoding="utf-8")
        assert "MixarCardElement::Count" in source


class TestGreetingName:
    def test_prefers_the_backend_name(self):
        assert account.derive_display_name("Rahul Sharma", "rs@mixar.app") == "Rahul"

    def test_title_cases_a_lowercase_name(self):
        assert account.derive_display_name("rahul", "x@mixar.app") == "Rahul"

    def test_keeps_existing_capitalization(self):
        assert account.derive_display_name("McDonald", "x@mixar.app") == "McDonald"

    def test_falls_back_to_the_email_local_part(self):
        assert account.derive_display_name("", "rahul@mixar.app") == "Rahul"

    def test_splits_a_dotted_local_part(self):
        assert account.derive_display_name("", "rahul.sharma@mixar.app") == "Rahul"

    def test_strips_trailing_digits(self):
        assert account.derive_display_name("", "rahul92@mixar.app") == "Rahul"

    def test_keeps_an_all_digit_local_part(self):
        """Stripping would leave nothing, and no greeting beats a blank one."""
        assert account.derive_display_name("", "12345@mixar.app") == "12345"

    def test_empty_when_nothing_usable(self):
        assert account.derive_display_name("", "") == ""
        assert account.derive_display_name("", "@mixar.app") == ""

    def test_card_greets_without_a_name_rather_than_a_dangling_comma(self):
        card = CARD_CC.read_text(encoding="utf-8")
        assert '"Welcome, %s !"' in card
        assert '"Welcome !"' in card


# ---------------------------------------------------------------------------
# Service contract
# ---------------------------------------------------------------------------


class TestSubscriptionService:
    def test_status_call_does_not_raise_on_404(self):
        """Free-tier users get a 404; raise_for_status would turn a normal
        account state into an exception on every poll."""
        from mixar.modules.common.api.services.subscription_service import (
            SubscriptionService,
        )

        src = inspect.getsource(SubscriptionService.get_status)
        assert "raise_for_status=False" in src

    def test_module_path_matches_the_backend_router(self):
        from mixar.modules.common.api.constants import APIModule

        assert APIModule.SUBSCRIPTIONS.value == "subscriptions"
