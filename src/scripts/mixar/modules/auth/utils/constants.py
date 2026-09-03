# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

AUTH_BASE_URL = "api/v1/auth"

# Preferred port for SSO callback server (falls back to OS-assigned if busy)
SSO_CALLBACK_PORT = 51731

# How long the desktop app waits for the browser to deliver the auth code.
# Corporate sign-in (IdP redirect + MFA push) routinely takes minutes; the
# old 120s window expired mid-login for enterprise users.
SSO_LOGIN_TIMEOUT_S = 300

# Per-connection read timeout on the loopback callback server. Endpoint
# security agents and browsers open connections without sending a request;
# without a timeout one such connection blocked the server forever.
SSO_CALLBACK_READ_TIMEOUT_S = 10
