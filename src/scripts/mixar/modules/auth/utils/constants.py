# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

AUTH_BASE_URL = "api/v1/auth"

# Preferred port for SSO callback server (falls back to OS-assigned if busy)
SSO_CALLBACK_PORT = 51731

# How long the desktop app waits for the browser to deliver the auth code.
# Corporate sign-in (IdP redirect + MFA push) routinely takes minutes, and a
# first-time user signs up in that same window (email OTP + onboarding
# questions) before the site hands the code back; 300s expired mid-signup.
SSO_LOGIN_TIMEOUT_S = 600

# Marks the desktop-login URL as opened by the app, so the website keeps a
# user who signs up instead of logging in on the handoff path (never the
# website's own signup -> downloads flow).
SSO_SOURCE_DESKTOP = "desktop"

# Per-connection read timeout on the loopback callback server. Endpoint
# security agents and browsers open connections without sending a request;
# without a timeout one such connection blocked the server forever.
SSO_CALLBACK_READ_TIMEOUT_S = 10
