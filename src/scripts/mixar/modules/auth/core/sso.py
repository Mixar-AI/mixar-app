# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
SSO authentication flow for Mixar desktop app.

Implements PKCE-based browser SSO login: opens the desktop-login page,
listens on a loopback HTTP server for the auth callback, and exchanges
the authorization code for access/refresh tokens.

Callback server contract
------------------------
* Threaded, with a per-connection read timeout. Endpoint-security agents,
  proxies and browsers routinely open a TCP connection to a freshly bound
  local port without sending a request. A single-threaded server with no
  read timeout blocked on that connection forever, never read the real
  callback, and left the UI on "Waiting for browser..." indefinitely.
* ``allow_reuse_address`` is off so another process cannot bind over the
  listening port (Windows honours SO_REUSEADDR that way). If the preferred
  port is busy the OS assigns one and it is passed to the frontend.
* The deadline is enforced by the wait loop, never by a handler.
"""

import base64
import hashlib
import json
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import requests

from ....config.config import get_frontend_url, get_server_url
from ....config.logging_config import get_logger
from ...common.network import classify_network_error, log_network_failure
from ..utils.constants import (
    SSO_CALLBACK_PORT,
    SSO_CALLBACK_READ_TIMEOUT_S,
    SSO_LOGIN_TIMEOUT_S,
)
from .auth import store_login_token_pair
from .device import get_device_id
from .sso_pages import SUCCESS_PAGE

logger = get_logger(__name__)


class CallbackState:
    """Shared between the wait loop and handler threads."""

    def __init__(self, expected_state):
        self.expected_state = expected_state
        self.code = None
        self.received = threading.Event()
        self._lock = threading.Lock()

    def accept(self, code):
        """Record the first accepted code; later ones are ignored."""
        with self._lock:
            if self.code is None:
                self.code = code
                self.received.set()


class _CallbackServer(ThreadingHTTPServer):
    daemon_threads = True  # a stalled peer must not delay shutdown
    allow_reuse_address = False


def _make_handler(state):
    class _CallbackHandler(BaseHTTPRequestHandler):
        # Applied to the accepted socket by StreamRequestHandler.setup();
        # a peer that connects and stays silent is dropped after this.
        timeout = SSO_CALLBACK_READ_TIMEOUT_S

        def do_GET(self):
            query = parse_qs(urlparse(self.path).query)
            code = query.get('code', [None])[0]
            received_state = query.get('state', [None])[0]

            if not code:
                # Stray request (favicon, probe, preflight) — answer and move on.
                self._reply(200, 'text/plain', b'OK')
                return

            # OAuth state check (RFC 6749 §10.12): a callback that did not
            # originate from this login attempt is rejected and the server
            # keeps serving so the legitimate one can still arrive.
            if not received_state or not secrets.compare_digest(
                received_state, state.expected_state
            ):
                logger.warning(
                    "SSO callback rejected: state mismatch (received=%r)",
                    bool(received_state),
                )
                self._reply(400, 'text/plain', b'state mismatch')
                return

            state.accept(code)
            self._reply(200, 'text/html', SUCCESS_PAGE)
            logger.info("SSO callback accepted: code received, state validated")

        def _reply(self, status, content_type, body):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass  # Suppress default stderr logging (also covers read timeouts)

    return _CallbackHandler


def start_callback_server(state):
    """Bind the loopback callback server on the preferred port or an OS-assigned one."""
    handler = _make_handler(state)
    try:
        return _CallbackServer(('127.0.0.1', SSO_CALLBACK_PORT), handler)
    except OSError:
        return _CallbackServer(('127.0.0.1', 0), handler)


def wait_for_code(server, state, timeout):
    """Serve until a code is accepted or ``timeout`` seconds elapse."""
    deadline = time.monotonic() + timeout
    while not state.received.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            logger.warning("SSO callback timed out after %ss", timeout)
            break
        server.timeout = min(remaining, 1.0)
        server.handle_request()
    return state.code


def _pkce_pair():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b'=').decode('ascii')
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode('ascii')).digest()
    ).rstrip(b'=').decode('ascii')
    return verifier, challenge


def _exchange_code(code, verifier):
    """POST the code to the backend. Returns (token_data, error_result)."""
    url = f"{get_server_url()}/api/v1/auth/desktop/token"
    payload = {'code': code, 'code_verifier': verifier}
    # Anti-abuse device signal: this exchange is the first moment the
    # backend sees the machine after a browser signup (best-effort)
    device_id = get_device_id()
    if device_id:
        payload['device_id'] = device_id

    try:
        response = requests.post(
            url,
            data=json.dumps(payload),
            headers={'Content-Type': 'application/json', 'accept': 'application/json'},
            timeout=30,
        )
    except requests.exceptions.RequestException as e:
        # First outbound HTTPS call the app makes after a fresh install:
        # TLS interception, proxies and firewalls all surface here.
        failure = classify_network_error(e, url=url)
        log_network_failure(logger, failure, "SSO token exchange")
        return None, {
            'success': False,
            'message': failure.user_text,
            'failure_kind': failure.kind,
        }

    logger.info("Token exchange response: %s", response.status_code)
    if response.status_code == 200:
        resp_data = response.json()
        # Tokens may be at top level or nested under "data"
        return resp_data.get('data', resp_data), None

    error_msg = f'Token exchange failed: {response.status_code}'
    try:
        detail = response.json().get('detail')
        if isinstance(detail, str):
            error_msg = detail
        elif isinstance(detail, dict):
            error_msg = detail.get('message', error_msg)
    except (ValueError, KeyError, AttributeError):
        pass
    logger.warning("Token exchange failed with status %d", response.status_code)
    return None, {'success': False, 'message': error_msg}


def sso_login(timeout=None):
    """Run SSO login flow via browser with PKCE.

    Opens browser to the desktop-login page, starts a loopback HTTP server
    to receive the auth callback, then exchanges the code for tokens.

    In Dev environment with dev_bypass.enabled, skips the browser flow
    and uses the configured credentials directly.

    Args:
        timeout: Seconds to wait for the browser callback
            (default SSO_LOGIN_TIMEOUT_S).

    Returns:
        dict with success, message, and optionally token / failure_kind.
    """
    if timeout is None:
        timeout = SSO_LOGIN_TIMEOUT_S

    try:
        from ....config.config import get_dev_bypass_credentials
        username, password = get_dev_bypass_credentials()
        if username and password:
            logger.info("Dev bypass active — logging in with username/password")
            from .auth import login
            return login(username, password)
    except Exception as e:
        logger.debug("Dev bypass failed: %s", e)

    verifier, challenge = _pkce_pair()
    expected_state = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b'=').decode('ascii')
    state = CallbackState(expected_state)

    try:
        server = start_callback_server(state)
    except OSError as e:
        logger.error("Failed to start auth server: %s", e)
        return {'success': False, 'message': f'Failed to start auth server: {e}'}

    actual_port = server.server_address[1]
    logger.info("SSO callback server listening on 127.0.0.1:%s", actual_port)

    # The frontend echoes `state` back unchanged in the loopback redirect.
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

    try:
        code = wait_for_code(server, state, timeout)
    finally:
        server.server_close()

    if not code:
        return {'success': False, 'message': 'Login was cancelled or timed out'}

    logger.info("Auth code received, exchanging for tokens...")
    try:
        token_data, error = _exchange_code(code, verifier)
    except Exception as e:
        logger.error("Token exchange error: %s", e)
        return {'success': False, 'message': f'Login error: {str(e)}'}
    if error:
        return error

    access_token = (token_data or {}).get('access_token')
    refresh_token_val = (token_data or {}).get('refresh_token')
    if not (access_token and access_token.strip() and refresh_token_val and refresh_token_val.strip()):
        logger.warning("Token exchange 200 but token pair was incomplete")
        return {'success': False, 'message': 'Incomplete token pair in response'}

    stored, storage_error = store_login_token_pair(access_token, refresh_token_val)
    if not stored:
        logger.error("Failed to store SSO token pair in safe storage")
        return {'success': False, 'message': storage_error}
    logger.info("SSO login successful — tokens stored")
    return {'success': True, 'message': 'Login successful', 'token': access_token}
