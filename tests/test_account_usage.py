# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Profile usage parsing and session-cache regression coverage."""

import sys
from types import ModuleType, SimpleNamespace

if "keyring" not in sys.modules:
    keyring_stub = ModuleType("keyring")
    keyring_stub.get_password = lambda *args, **kwargs: None
    keyring_stub.set_password = lambda *args, **kwargs: None
    keyring_stub.delete_password = lambda *args, **kwargs: None
    sys.modules["keyring"] = keyring_stub

from mixar.modules.auth.core import auth
from mixar.modules.space_mixie_chat.core import account_usage
from mixar.modules.space_mixie_chat.ui import topbar


class _Response:
    status_code = 200

    @staticmethod
    def json():
        return {
            "email": "artist@example.com",
            "credits": 12_345,
            "plan_slug": "studio",
            "plan_name": "Studio",
            "trial_days_remaining": 4,
            "team_name": "Design",
            "team_role": "member",
            "team_is_active": True,
        }


def _wm():
    return SimpleNamespace(
        mixie_account_credits=0,
        mixie_account_plan_name="",
        mixie_account_trial_days=-1,
        mixie_account_team_name="",
        mixie_account_team_role="",
        mixie_account_team_is_active=False,
        mixie_account_loaded=False,
        mixie_account_loading=False,
        mixie_account_error="",
        mixie_account_refreshed_at=0.0,
    )


def test_get_user_info_preserves_profile_usage_fields(monkeypatch):
    monkeypatch.setattr(auth, "get_access_token", lambda: "token")
    monkeypatch.setattr(auth.requests, "get", lambda *args, **kwargs: _Response())

    result = auth.get_user_info()

    assert result["status"] == "success"
    assert result["data"] == {
        "email": "artist@example.com",
        "credits": 12_345,
        "plan_name": "Studio",
        "plan_slug": "studio",
        "trial_days_remaining": 4,
        "team_name": "Design",
        "team_role": "member",
        "team_is_active": True,
    }


def test_apply_user_info_uses_safe_fallbacks_and_marks_loaded(monkeypatch):
    wm = _wm()
    monkeypatch.setattr(account_usage.time, "monotonic", lambda: 42.0)

    account_usage.apply_user_info(wm, {"credits": 0, "plan_slug": "free"})

    assert wm.mixie_account_credits == 0
    assert wm.mixie_account_plan_name == "free"
    assert wm.mixie_account_trial_days == -1
    assert wm.mixie_account_loaded is True
    assert wm.mixie_account_loading is False
    assert wm.mixie_account_refreshed_at == 42.0


def test_clear_removes_previous_users_account_summary():
    wm = _wm()
    wm.mixie_account_credits = 999
    wm.mixie_account_plan_name = "Studio"
    wm.mixie_account_team_name = "Old team"
    wm.mixie_account_loaded = True

    account_usage.clear(wm)

    assert wm.mixie_account_credits == 0
    assert wm.mixie_account_plan_name == ""
    assert wm.mixie_account_team_name == ""
    assert wm.mixie_account_loaded is False


def test_subtitle_falls_back_to_free_plan_and_omits_absent_context():
    wm = _wm()

    assert topbar._account_subtitle(wm) == "Free"


def test_subtitle_joins_plan_trial_and_team_pool():
    wm = _wm()
    wm.mixie_account_plan_name = "Studio"
    wm.mixie_account_trial_days = 4
    wm.mixie_account_team_is_active = True
    wm.mixie_account_team_name = "Design"

    assert topbar._account_subtitle(wm) == "Studio   4 days left   Design pool"


def test_pill_label_passes_short_emails_through_untouched():
    assert topbar._pill_label("artist@example.com") == "artist@example.com"


def test_pill_label_truncates_long_emails_to_a_bounded_width():
    long_email = "a-very-long-address@studio-example-company.com"

    label = topbar._pill_label(long_email)

    assert len(label) == topbar.PILL_MAX_CHARS
    assert label.endswith("…")
    assert long_email.startswith(label[:-1])


def test_subtitle_singularises_a_one_day_trial():
    wm = _wm()
    wm.mixie_account_trial_days = 1

    assert topbar._account_subtitle(wm) == "Free   1 day left"
