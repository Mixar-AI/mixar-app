# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
SSO authentication flow for Mixar desktop app.

Implements PKCE-based browser SSO login: opens the desktop-login page,
listens on a local HTTP server for the auth callback, and exchanges
the authorization code for access/refresh tokens.
"""

import base64
import hashlib
import json
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import requests

from ....config.config import get_frontend_url, get_server_url
from ....config.logging_config import get_logger
from ..utils.constants import SSO_CALLBACK_PORT
from .device import get_device_id
from .auth import store_login_token_pair

logger = get_logger(__name__)

_SUCCESS_PAGE = b"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Login Successful \xe2\x80\x94 Mixar</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Inter', sans-serif;
      background: #0a0a0a;
      color: #fff;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 2rem;
      -webkit-font-smoothing: antialiased;
    }
    .card {
      width: 100%;
      max-width: 480px;
      background: rgba(255, 255, 255, 0.02);
      border: 1px solid rgba(0, 192, 199, 0.15);
      border-radius: 24px;
      padding: 3rem;
      backdrop-filter: blur(20px);
      text-align: center;
      animation: fadeUp 0.6s ease forwards;
    }
    .check {
      width: 64px;
      height: 64px;
      background: rgba(34, 197, 94, 0.1);
      border: 1px solid rgba(34, 197, 94, 0.3);
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      margin: 0 auto 1.5rem;
    }
    .check svg { color: #22c55e; }
    h1 {
      font-size: 2rem;
      font-weight: 600;
      margin-bottom: 0.75rem;
      background: linear-gradient(135deg, #00C0C7 0%, #85C449 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
    }
    p { font-size: 1rem; color: rgba(255, 255, 255, 0.5); line-height: 1.6; }
    @keyframes fadeUp {
      from { opacity: 0; transform: translateY(40px); }
      to   { opacity: 1; transform: translateY(0); }
    }
  </style>
</head>
<body>
  <div class="card">
    <div class="check">
      <svg width="32" height="32" viewBox="0 0 24 24" fill="none"
           stroke="currentColor" stroke-width="2.5">
        <polyline points="20 6 9 17 4 12" />
      </svg>
    </div>
    <h1>Login Successful</h1>
    <p>You can close this tab and return to Mixar.</p>
  </div>
  <script>window.close();</script>
</body>
</html>"""


def sso_login(timeout=120):
    """Run SSO login flow via browser with PKCE.

    Opens browser to the desktop-login page, starts a local HTTP server
    to receive the auth callback, then exchanges the code for tokens.
    Keeps serving until the code is received or timeout expires.

    In Dev environment with dev_bypass.enabled, skips the browser flow
    and uses the configured sso_token directly.

    Args:
        timeout: Seconds to wait for browser callback (default 120).

    Returns:
        dict with success, message, and optionally token.
    """
    try:
        from ....config.config import get_dev_bypass_credentials
        username, password = get_dev_bypass_credentials()
        if username and password:
            logger.info("Dev bypass active — logging in with username/password")
            from .auth import login
            return login(username, password)
    except Exception as e:
        logger.debug("Dev bypass failed: %s", e)

    # Generate PKCE verifier + challenge
    verifier = base64.urlsafe_b64encode(
        secrets.token_bytes(32)
    ).rstrip(b'=').decode('ascii')
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode('ascii')).digest()
    ).rstrip(b'=').decode('ascii')

    # Generate OAuth state nonce (RFC 6749 §10.12 CSRF defense). Must round-trip
    # through the frontend and back unchanged on the localhost callback. Any
    # callback whose state doesn't match this value is rejected.
    expected_state = base64.urlsafe_b64encode(
        secrets.token_bytes(32)
    ).rstrip(b'=').decode('ascii')

    code_result = {'code': None}

    class _CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            code = query.get('code', [None])[0]
            received_state = query.get('state', [None])[0]

            # If a code was supplied, gate it on a matching state. Missing or
            # mismatched state means this callback didn't originate from the
            # SSO flow we initiated — reject with 400 and keep serving so the
            # legitimate callback can still win the race.
            if code:
                if not received_state or not secrets.compare_digest(
                    received_state, expected_state
                ):
                    logger.warning(
                        "SSO callback rejected: state mismatch "
                        "(received=%r, expected_len=%d)",
                        bool(received_state), len(expected_state),
                    )
                    self.send_response(400)
                    self.send_header('Content-Type', 'text/plain')
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    self.wfile.write(b'state mismatch')
                    return

                code_result['code'] = code
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.send_header('Connection', 'close')
                self.end_headers()
                self.wfile.write(_SUCCESS_PAGE)
                logger.info("SSO callback accepted: code received, state validated")
            else:
                # Stray request (favicon, etc.) — respond OK and keep serving
                self.send_response(200)
                self.send_header('Content-Type', 'text/plain')
                self.send_header('Connection', 'close')
                self.end_headers()
                self.wfile.write(b'OK')

        def log_message(self, format, *args):
            pass  # Suppress default stderr logging

    # Start local callback server (try preferred port, fall back to OS-assigned)
    server = None
    try:
        server = HTTPServer(('127.0.0.1', SSO_CALLBACK_PORT), _CallbackHandler)
    except OSError:
        try:
            server = HTTPServer(('127.0.0.1', 0), _CallbackHandler)
        except OSError as e:
            logger.error("Failed to start auth server: %s", e)
            return {'success': False, 'message': f'Failed to start auth server: {e}'}

    actual_port = server.server_address[1]
    logger.info("SSO callback server listening on 127.0.0.1:%s", actual_port)

    # Open browser for SSO (uses frontend URL for the login page).
    # Frontend echoes `state` back unchanged in the localhost redirect; the
    # callback handler above validates it.
    sso_url = (
        f"{get_frontend_url()}/app/desktop-login"
        f"?port={actual_port}&code_challenge={challenge}"
        f"&code_challenge_method=S256&state={expected_state}"
    )
    try:
        webbrowser.open(sso_url)
        logger.info("Opened browser for SSO: %s", sso_url)
    except Exception as e:
        server.server_close()
        logger.error("Failed to open browser: %s", e)
        return {'success': False, 'message': f'Failed to open browser: {e}'}

    # Keep handling requests until the code arrives or we time out.
    # This loop naturally handles stray requests (favicon, preflight, etc.)
    deadline = time.time() + timeout
    while not code_result['code']:
        remaining = deadline - time.time()
        if remaining <= 0:
            logger.warning("SSO callback timed out after %ss", timeout)
            break
        server.timeout = min(remaining, 1.0)
        server.handle_request()

    server.server_close()

    code = code_result['code']
    if not code:
        return {'success': False, 'message': 'Login was cancelled or timed out'}

    logger.info("Auth code received, exchanging for tokens...")

    # Exchange code for tokens
    try:
        url = f"{get_server_url()}/api/v1/auth/desktop/token"
        payload = {'code': code, 'code_verifier': verifier}
        # Anti-abuse device signal: this exchange is the first moment the
        # backend sees the machine after a browser signup (best-effort)
        device_id = get_device_id()
        if device_id:
            payload['device_id'] = device_id
        body = json.dumps(payload)

        response = requests.post(
            url,
            data=body,
            headers={
                'Content-Type': 'application/json',
                'accept': 'application/json',
            },
            timeout=30,
        )
        logger.info("Token exchange response: %s", response.status_code)

        if response.status_code == 200:
            resp_data = response.json()
            # Tokens may be at top level or nested under "data"
            token_data = resp_data.get('data', resp_data)
            access_token = token_data.get('access_token')
            refresh_token_val = token_data.get('refresh_token')

            if (
                access_token
                and access_token.strip()
                and refresh_token_val
                and refresh_token_val.strip()
            ):
                stored, storage_error = store_login_token_pair(
                    access_token,
                    refresh_token_val,
                )
                if not stored:
                    logger.error("Failed to store SSO token pair in safe storage")
                    return {'success': False, 'message': storage_error}
                logger.info("SSO login successful — tokens stored")
                return {
                    'success': True,
                    'message': 'Login successful',
                    'token': access_token,
                }
            logger.warning("Token exchange 200 but token pair was incomplete")
            return {'success': False, 'message': 'Incomplete token pair in response'}

        error_msg = f'Token exchange failed: {response.status_code}'
        try:
            error_data = response.json()
            logger.warning("Token exchange failed with status %d", response.status_code)
            detail = error_data.get('detail')
            if isinstance(detail, str):
                error_msg = detail
            elif isinstance(detail, dict):
                error_msg = detail.get('message', error_msg)
        except (ValueError, KeyError):
            pass
        return {'success': False, 'message': error_msg}

    except requests.exceptions.Timeout:
        logger.warning("Token exchange timed out")
        return {'success': False, 'message': 'Token exchange timed out'}
    except requests.exceptions.ConnectionError:
        logger.warning("Token exchange connection error")
        return {'success': False, 'message': 'Unable to connect to server'}
    except Exception as e:
        logger.error("Token exchange error: %s", e)
        return {'success': False, 'message': f'Login error: {str(e)}'}
