# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Desktop-login URL contract with the website.

A first-time user who signs up instead of logging in must come back to the
app: the website keys that path on ``source=desktop`` and the window must be
long enough for an email OTP plus the onboarding questions.
"""

from urllib.parse import parse_qs, urlparse

from mixar.modules.auth.core import sso


def test_desktop_login_url_carries_pkce_state_and_source(monkeypatch):
    monkeypatch.setattr(sso, "get_frontend_url", lambda: "https://mixar.app")

    url = urlparse(sso.desktop_login_url(51731, "chal-_1", "st-_2"))

    assert (url.scheme, url.netloc, url.path) == ("https", "mixar.app", "/app/desktop-login")
    assert parse_qs(url.query) == {
        "port": ["51731"],
        "code_challenge": ["chal-_1"],
        "code_challenge_method": ["S256"],
        "state": ["st-_2"],
        "source": ["desktop"],
    }


def test_login_window_covers_a_browser_signup():
    assert sso.SSO_LOGIN_TIMEOUT_S >= 600
