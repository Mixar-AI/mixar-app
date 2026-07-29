# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Authentication utilities for Mixar
"""

import hashlib
import json
import platform
import threading
import time
import urllib.parse
import uuid
import webbrowser

import requests

from ....config.config import get_server_url
from ....config.logging_config import get_logger
from ..utils.constants import AUTH_BASE_URL
from .device import get_device_id

logger = get_logger(__name__)

# Windows-specific credential handling to match C++ implementation
# C++ uses TargetName format: "MixarSafeStorage@AccessToken" and "MixarSafeStorage@RefreshToken"
# Python keyring uses a different format, causing inconsistency

_is_windows = platform.system() == "Windows"

if _is_windows:
    import ctypes
    from ctypes import wintypes

    # Windows Credential Manager constants
    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2

    # Use username@service format (matches Python keyring's compound format)
    WIN_TARGET_NAME_ACCESS = "AccessToken@MixarSafeStorage"
    WIN_TARGET_NAME_REFRESH = "RefreshToken@MixarSafeStorage"
    WIN_TARGET_NAME_REFRESH_ATTEMPT = "RefreshAttempt@MixarSafeStorage"

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    # use_last_error=True so ctypes.get_last_error() returns correct Win32 error codes
    advapi32 = ctypes.WinDLL('advapi32', use_last_error=True)

    CredReadW = advapi32.CredReadW
    CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
    CredReadW.restype = wintypes.BOOL

    CredWriteW = advapi32.CredWriteW
    CredWriteW.argtypes = [ctypes.POINTER(CREDENTIAL), wintypes.DWORD]
    CredWriteW.restype = wintypes.BOOL

    CredDeleteW = advapi32.CredDeleteW
    CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    CredDeleteW.restype = wintypes.BOOL

    CredFree = advapi32.CredFree
    CredFree.argtypes = [ctypes.c_void_p]
    CredFree.restype = None

    def _win_get_password(target_name: str) -> str:
        """Read password from Windows Credential Manager using exact C++ format."""
        cred_ptr = ctypes.POINTER(CREDENTIAL)()
        if CredReadW(target_name, CRED_TYPE_GENERIC, 0, ctypes.byref(cred_ptr)):
            try:
                cred = cred_ptr.contents
                if cred.CredentialBlobSize > 0 and cred.CredentialBlob:
                    blob_bytes = bytes(cred.CredentialBlob[:cred.CredentialBlobSize])
                    return blob_bytes.decode("utf-8")
            finally:
                CredFree(cred_ptr)
        return ""

    def _win_set_password(target_name: str, username: str, password: str) -> bool:
        """Write password to Windows Credential Manager using exact C++ format."""
        password_bytes = password.encode("utf-8")
        blob_size = len(password_bytes)
        blob = (ctypes.c_ubyte * blob_size)(*password_bytes)

        cred = CREDENTIAL()
        cred.Type = CRED_TYPE_GENERIC
        cred.TargetName = target_name
        cred.CredentialBlobSize = blob_size
        cred.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
        cred.Persist = CRED_PERSIST_LOCAL_MACHINE
        cred.UserName = username

        return bool(CredWriteW(ctypes.byref(cred), 0))

    def _win_delete_password(target_name: str) -> bool:
        """Delete password from Windows Credential Manager."""
        result = CredDeleteW(target_name, CRED_TYPE_GENERIC, 0)
        if not result:
            # Check if it's "not found" error (ERROR_NOT_FOUND = 1168)
            error = ctypes.get_last_error()
            if error == 1168:  # ERROR_NOT_FOUND
                return True  # Nothing to delete is success
        return bool(result)
else:
    import keyring


def get_access_token():
    """Get the stored access token from system credential storage."""
    try:
        if _is_windows:
            # Use Windows Credential Manager directly with C++ compatible format
            token = _win_get_password(WIN_TARGET_NAME_ACCESS)
        else:
            # Use keyring for macOS/Linux
            token = keyring.get_password("MixarSafeStorage", "AccessToken")
        return token if token else ""
    except Exception as e:
        logger.warning(f"Failed to retrieve access token: {e}")
        return ""


def store_access_token(token):
    """Store the access token in system credential storage."""
    try:
        if _is_windows:
            # Use Windows Credential Manager directly with C++ compatible format
            return _win_set_password(WIN_TARGET_NAME_ACCESS, "AccessToken", token)
        else:
            # Use keyring for macOS/Linux
            keyring.set_password("MixarSafeStorage", "AccessToken", token)
            return True
    except Exception as e:
        logger.error(f"Failed to store access token: {e}")
        return False


def delete_access_token():
    """Delete the access token from system credential storage."""
    try:
        if _is_windows:
            # Use Windows Credential Manager directly with C++ compatible format
            return _win_delete_password(WIN_TARGET_NAME_ACCESS)
        else:
            # Use keyring for macOS/Linux
            keyring.delete_password("MixarSafeStorage", "AccessToken")
            return True
    except Exception as e:
        logger.warning(f"Failed to delete access token: {e}")
        return False


def get_refresh_token():
    """Get the stored refresh token from system credential storage."""
    try:
        if _is_windows:
            # Use Windows Credential Manager directly with C++ compatible format
            token = _win_get_password(WIN_TARGET_NAME_REFRESH)
        else:
            # Use keyring for macOS/Linux
            token = keyring.get_password("MixarSafeStorage", "RefreshToken")
        return token if token else ""
    except Exception as e:
        logger.warning(f"Failed to retrieve refresh token: {e}")
        return ""


def store_refresh_token(token):
    """Store the refresh token in system credential storage."""
    try:
        if _is_windows:
            # Use Windows Credential Manager directly with C++ compatible format
            return _win_set_password(WIN_TARGET_NAME_REFRESH, "RefreshToken", token)
        else:
            # Use keyring for macOS/Linux
            keyring.set_password("MixarSafeStorage", "RefreshToken", token)
            return True
    except Exception as e:
        logger.error(f"Failed to store refresh token: {e}")
        return False


def delete_refresh_token():
    """Delete the refresh token from system credential storage."""
    try:
        if _is_windows:
            # Use Windows Credential Manager directly with C++ compatible format
            return _win_delete_password(WIN_TARGET_NAME_REFRESH)
        else:
            # Use keyring for macOS/Linux
            keyring.delete_password("MixarSafeStorage", "RefreshToken")
            return True
    except Exception as e:
        logger.warning(f"Failed to delete refresh token: {e}")
        return False


def _refresh_token_digest(token):
    """Return a non-reversible identity for a refresh-token attempt."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _load_persisted_refresh_attempt():
    """Return ``(storage_available, attempt_or_none)`` from safe storage.

    ``storage_available`` is False only when safe storage itself cannot be
    read (or an invalid marker cannot be removed). A marker whose *content*
    is invalid is discarded and reported as absent: its idempotency key is
    unrecoverable, so the only safe way forward is a fresh logical attempt.
    At worst the backend rejects that attempt as a definitive replay and the
    user re-authenticates once — instead of refresh being wedged forever.
    """
    try:
        if _is_windows:
            raw = _win_get_password(WIN_TARGET_NAME_REFRESH_ATTEMPT)
        else:
            raw = keyring.get_password("MixarSafeStorage", "RefreshAttempt")
    except Exception as e:
        logger.error(f"Failed to read pending refresh attempt: {e}")
        return False, None
    if not raw:
        return True, None

    attempt = None
    try:
        parsed = json.loads(raw)
        digest = parsed.get("refresh_token_digest")
        idempotency_key = parsed.get("idempotency_key")
        parsed_key = uuid.UUID(idempotency_key)
        if (
            isinstance(digest, str)
            and isinstance(idempotency_key, str)
            and len(digest) == 64
            and int(digest, 16) >= 0
            and parsed_key.version == 4
            and str(parsed_key) == idempotency_key
        ):
            attempt = {
                "refresh_token_digest": digest,
                "idempotency_key": idempotency_key,
            }
    except (AttributeError, TypeError, ValueError):
        attempt = None

    if attempt is None:
        logger.error("Stored refresh attempt is invalid; discarding it")
        if not _delete_persisted_refresh_attempt():
            return False, None
        return True, None
    return True, attempt


def _persist_refresh_attempt(attempt):
    """Atomically store digest + idempotency key before the HTTP request."""
    try:
        raw = json.dumps(
            {
                "refresh_token_digest": attempt["refresh_token_digest"],
                "idempotency_key": attempt["idempotency_key"],
            },
            separators=(",", ":"),
        )
        if _is_windows:
            return _win_set_password(
                WIN_TARGET_NAME_REFRESH_ATTEMPT,
                "RefreshAttempt",
                raw,
            )
        keyring.set_password("MixarSafeStorage", "RefreshAttempt", raw)
        return True
    except Exception as e:
        logger.error(f"Failed to persist pending refresh attempt: {e}")
        return False


def _delete_persisted_refresh_attempt():
    """Delete the durable logical-attempt marker; absence is success."""
    try:
        if _is_windows:
            return _win_delete_password(WIN_TARGET_NAME_REFRESH_ATTEMPT)
        raw = keyring.get_password("MixarSafeStorage", "RefreshAttempt")
        if not raw:
            return True
        keyring.delete_password("MixarSafeStorage", "RefreshAttempt")
        return True
    except Exception as e:
        logger.error(f"Failed to delete pending refresh attempt: {e}")
        return False


def login(username, password):
    """
    Authenticate user with username and password.

    Returns dict with:
        - success: bool
        - message: str
        - token: str (only if success)
    """
    try:
        url = f"{get_server_url()}/api/v1/auth/login"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "accept": "application/json",
        }
        form_fields = {
            "username": username,
            "password": password,
        }
        # Anti-abuse device signal (one trial per machine); best-effort
        device_id = get_device_id()
        if device_id:
            form_fields["device_id"] = device_id
        data = urllib.parse.urlencode(form_fields)

        response = requests.post(url, headers=headers, data=data, timeout=30)

        if response.status_code == 200:
            response_data = response.json()
            access_token = response_data.get("access_token")
            refresh_token = response_data.get("refresh_token")
            if (
                access_token
                and access_token.strip()
                and refresh_token
                and refresh_token.strip()
            ):
                stored, storage_error = store_login_token_pair(
                    access_token,
                    refresh_token,
                )
                if stored:
                    logger.info("Login successful")
                    return {
                        "success": True,
                        "message": "Login successful",
                        "token": access_token,
                    }
                else:
                    return {
                        "success": False,
                        "message": storage_error,
                    }
            else:
                return {
                    "success": False,
                    "message": "Incomplete token pair in login response",
                }
        else:
            # Parse error message from response
            error_message = f"Authentication failed: {response.status_code}"
            try:
                error_data = response.json()
                detail = error_data.get("detail")
                if isinstance(detail, dict):
                    error_message = detail.get("message", error_message)
                elif detail:
                    error_message = detail
            except (ValueError, KeyError) as e:
                logger.debug(f"Could not parse error response: {e}")
            logger.warning(f"Login failed: {error_message}")
            return {
                "success": False,
                "message": error_message,
            }

    except requests.exceptions.Timeout:
        return {
            "success": False,
            "message": "Connection timed out",
        }
    except requests.exceptions.ConnectionError:
        return {
            "success": False,
            "message": "Unable to connect to server",
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Login error: {str(e)}",
        }


# The backend rotates refresh tokens: each successful refresh invalidates the
# token that was sent. Concurrent refreshes (e.g. several request-pool threads
# hitting 401 at the same expiry instant) must therefore be single-flighted.
#
# A network timeout is ambiguous: the backend may have rotated the token even
# though the client did not receive the response. Retrying that logical
# operation with a new idempotency key would look like refresh-token theft.
# Keep the original token + key until the operation has a definitive outcome,
# while separately caching its result for a few seconds to collapse a burst of
# waiting threads.
_refresh_lock = threading.Lock()
_last_refresh = None
_pending_refresh = None
_REFRESH_SUCCESS_REUSE_WINDOW = 10.0  # seconds
_REFRESH_FAILURE_COALESCE_WINDOW = 3.0  # seconds


def _clear_refresh_state():
    """Clear process-local refresh state after an explicit credential change."""
    with _refresh_lock:
        return _clear_refresh_state_locked()


def _clear_refresh_state_locked():
    """Clear process and durable attempt state while holding ``_refresh_lock``."""
    global _last_refresh, _pending_refresh
    _last_refresh = None
    _pending_refresh = None
    return _delete_persisted_refresh_attempt()


def _credentials_snapshot():
    """Return the current pair used to guard cached results against staleness."""
    return get_access_token(), get_refresh_token()


def _get_or_create_refresh_attempt_locked(refresh_token):
    """Recover or durably create the logical attempt for ``refresh_token``."""
    global _pending_refresh
    digest = _refresh_token_digest(refresh_token)
    storage_available, persisted = _load_persisted_refresh_attempt()
    if not storage_available:
        return None

    if persisted is not None and persisted["refresh_token_digest"] != digest:
        # The credential lineage changed (successful login/rotation/logout).
        # The old marker must be removed before a new attempt can be safe.
        if not _delete_persisted_refresh_attempt():
            return None
        persisted = None

    if persisted is not None:
        _pending_refresh = {
            "refresh_token": refresh_token,
            "refresh_token_digest": digest,
            "idempotency_key": persisted["idempotency_key"],
        }
        return _pending_refresh

    if (
        _pending_refresh is None
        or _pending_refresh.get("refresh_token_digest") != digest
    ):
        _pending_refresh = {
            "refresh_token": refresh_token,
            "refresh_token_digest": digest,
            "idempotency_key": str(uuid.uuid4()),
        }

    # Safe-storage persistence happens before requests.post. If it fails, the
    # request must not be sent because a restart could no longer retry safely.
    if not _persist_refresh_attempt(_pending_refresh):
        _pending_refresh = None
        return None
    return _pending_refresh


def refresh_access_token():
    """
    Refresh the access token using the stored refresh token.

    Thread-safe and single-flighted: concurrent callers are serialized and
    reuse the recently completed result. Ambiguous retries keep using the same
    Idempotency-Key and refresh token until the backend gives a definitive
    response.

    Returns dict with:
        - success: bool
        - message: str
        - token: str (new access token, only if success)
    """
    global _last_refresh, _pending_refresh
    with _refresh_lock:
        credentials = _credentials_snapshot()
        if _last_refresh is not None:
            completed_at, cached_credentials, cached_result, reuse_window = _last_refresh
            age = time.monotonic() - completed_at
            if cached_credentials == credentials and 0 <= age < reuse_window:
                return cached_result

        refresh_token = credentials[1]
        if not refresh_token:
            _clear_refresh_state_locked()
            return {
                "success": False,
                "message": "No refresh token available",
                "retryable": False,
            }

        attempt = _get_or_create_refresh_attempt_locked(refresh_token)
        if attempt is None:
            return {
                "success": False,
                "message": "Unable to safely persist token refresh attempt",
                "retryable": True,
            }
        result, retain_attempt = _refresh_access_token_locked(
            attempt["refresh_token"],
            attempt["idempotency_key"],
        )

        if not retain_attempt:
            _clear_refresh_state_locked()

        # Cache success long enough for all 401 callers to observe the rotated
        # access token. Cache an ambiguous failure only briefly; after this
        # window a later caller retries the retained logical attempt.
        if result.get("success") or retain_attempt:
            reuse_window = (
                _REFRESH_SUCCESS_REUSE_WINDOW
                if result.get("success")
                else _REFRESH_FAILURE_COALESCE_WINDOW
            )
            _last_refresh = (
                time.monotonic(),
                _credentials_snapshot(),
                result,
                reuse_window,
            )
        else:
            _last_refresh = None
        return result


def _restore_token_pair(access_token, refresh_token):
    """Best-effort rollback when only half of a rotated pair was persisted."""
    refresh_restored = (
        store_refresh_token(refresh_token) if refresh_token else delete_refresh_token()
    )
    access_restored = (
        store_access_token(access_token) if access_token else delete_access_token()
    )
    if not access_restored or not refresh_restored:
        logger.error("Failed to restore credentials after partial token rotation")


def _replace_token_pair_locked(new_access_token, new_refresh_token):
    """Replace both credentials while fenced against token refresh."""
    old_access_token, old_refresh_token = _credentials_snapshot()
    if not store_refresh_token(new_refresh_token):
        _restore_token_pair(old_access_token, old_refresh_token)
        return False, "Failed to store refresh token"
    if not store_access_token(new_access_token):
        _restore_token_pair(old_access_token, old_refresh_token)
        return False, "Failed to store access token"
    return True, None


def store_login_token_pair(access_token, refresh_token):
    """Atomically fence an explicit login pair against refresh operations."""
    with _refresh_lock:
        stored, error = _replace_token_pair_locked(access_token, refresh_token)
        if stored:
            # Login establishes a new credential lineage. A stale durable
            # attempt is harmless if deletion fails (digest mismatch prevents
            # replay), but report it so safe-storage health remains visible.
            if not _clear_refresh_state_locked():
                logger.error("Failed to clear pending refresh state after login")
        return stored, error


def clear_credentials():
    """Delete the credential pair and all refresh-attempt state under one fence."""
    with _refresh_lock:
        access_deleted = delete_access_token()
        refresh_deleted = delete_refresh_token()
        state_cleared = _clear_refresh_state_locked()
        return access_deleted and refresh_deleted and state_cleared


def _store_rotated_token_pair(old_refresh_token, new_access_token, new_refresh_token):
    """Persist a rotated pair; return ``(stored, message, superseded)``."""
    _, current_refresh_token = _credentials_snapshot()
    if current_refresh_token != old_refresh_token:
        # An explicit login (or another credential owner) won the race while
        # the HTTP request was in flight. Never overwrite that newer pair.
        return (
            False,
            "Credentials changed while token refresh was in progress",
            True,
        )

    stored, error = _replace_token_pair_locked(new_access_token, new_refresh_token)
    if not stored:
        return False, error, False

    return True, None, False


def _refresh_access_token_locked(refresh_token, idempotency_key):
    """Perform one attempt. Return ``(public_result, retain_attempt)``."""

    try:
        url = f"{get_server_url()}/api/v1/auth/refresh"
        headers = {
            "Content-Type": "application/json",
            "accept": "application/json",
            "Idempotency-Key": idempotency_key,
        }
        data = json.dumps({"refresh_token": refresh_token})

        response = requests.post(url, headers=headers, data=data, timeout=30)

        if response.status_code == 200:
            response_data = response.json()
            new_access_token = response_data.get("access_token")
            new_refresh_token = response_data.get("refresh_token")

            if (
                new_access_token
                and new_access_token.strip()
                and new_refresh_token
                and new_refresh_token.strip()
            ):
                stored, storage_error, superseded = _store_rotated_token_pair(
                    refresh_token,
                    new_access_token,
                    new_refresh_token,
                )
                if not stored:
                    return ({
                        "success": False,
                        "message": storage_error,
                        "retryable": True,
                    }, not superseded)
                logger.info("Token refreshed successfully")
                return ({
                    "success": True,
                    "message": "Token refreshed successfully",
                    "token": new_access_token,
                    "retryable": False,
                }, False)
            else:
                return ({
                    "success": False,
                    "message": "Incomplete token pair in refresh response",
                    "retryable": True,
                }, True)
        else:
            # Parse error message from response
            error_message = f"Token refresh failed: {response.status_code}"
            try:
                error_data = response.json()
                detail = error_data.get("detail")
                if isinstance(detail, dict):
                    error_message = detail.get("message", error_message)
                elif detail:
                    error_message = detail
            except (ValueError, KeyError) as e:
                logger.debug(f"Could not parse error response: {e}")

            # Only delete tokens on auth failures (401/403), not on other errors
            if response.status_code in (401, 403):
                logger.warning(f"Token refresh failed with {response.status_code}: {error_message}")
                # Do not let a stale response delete credentials established by
                # a login that completed while this request was in flight.
                if get_refresh_token() == refresh_token:
                    delete_access_token()
                    delete_refresh_token()
            else:
                # Other error (4xx, 5xx) - keep tokens for retry
                logger.warning(f"Token refresh failed: {error_message}")
            result = {
                "success": False,
                "message": error_message,
                "retryable": response.status_code not in (401, 403),
            }
            return result, response.status_code not in (401, 403)

    except requests.exceptions.Timeout:
        return ({
            "success": False,
            "message": "Connection timed out",
            "retryable": True,
        }, True)
    except requests.exceptions.ConnectionError:
        return ({
            "success": False,
            "message": "Unable to connect to server",
            "retryable": True,
        }, True)
    except Exception as e:
        # The request may already have reached the backend. Retaining the
        # logical attempt is safer than replaying the refresh token with a new
        # idempotency key.
        return ({
            "success": False,
            "message": f"Token refresh error: {str(e)}",
            "retryable": True,
        }, True)


def get_user_info():
    """Get the user info from the /me endpoint"""
    token = get_access_token()
    if not token:
        return None

    response_data = {
        "status": "failure",
        "message": "No access token found",
        "data": {
            "email": "Unknown",
            "credits": 0,
            "plan_name": "",
            "plan_slug": "",
            "trial_days_remaining": None,
            "team_name": "",
            "team_role": "",
            "team_is_active": False,
        },
    }

    try:
        url = f"{get_server_url()}/{AUTH_BASE_URL}/me"
        headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {token}",
        }

        response = requests.get(url, headers=headers, timeout=10)

        # Handle 401 with automatic token refresh
        if response.status_code == 401:
            logger.debug("Got 401 in get_user_info, attempting token refresh")
            refresh_result = refresh_access_token()

            if refresh_result.get("success"):
                # Retry with new token
                new_token = get_access_token()
                headers["Authorization"] = f"Bearer {new_token}"
                response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            user_data = response.json()
            response_data["status"] = "success"
            response_data["message"] = "User info fetched successfully"
            response_data["data"]["email"] = user_data.get("email", "Unknown")
            response_data["data"]["credits"] = user_data.get("credits", 0)
            response_data["data"]["plan_name"] = user_data.get("plan_name") or ""
            response_data["data"]["plan_slug"] = user_data.get("plan_slug") or ""
            response_data["data"]["trial_days_remaining"] = user_data.get(
                "trial_days_remaining"
            )
            response_data["data"]["team_name"] = user_data.get("team_name") or ""
            response_data["data"]["team_role"] = user_data.get("team_role") or ""
            response_data["data"]["team_is_active"] = bool(
                user_data.get("team_is_active", False)
            )
            return response_data
        else:
            logger.warning(f"Error getting user info: {response.status_code}")
            response_data["status"] = "failure"
            response_data["message"] = (
                f"Error getting user info: {response.status_code}"
            )
            response_data["data"]["email"] = "Unknown"
            response_data["data"]["credits"] = 0
            return response_data

    except Exception as e:
        logger.warning(f"Error getting user info: {e}")
        response_data["status"] = "failure"
        response_data["message"] = f"Connection error: {str(e)}"
        response_data["data"]["email"] = "Unknown"
        response_data["data"]["credits"] = 0
        return response_data


def create_dashboard_handoff_url(source="texture_painting", target=None):
    """
    Create a one-time auth handoff URL for the web dashboard.

    Args:
        source: Identifies where the handoff originated (analytics/routing).
        target: Optional post-auth destination (e.g. the manage-subscription
            page). Forwarded to the backend so the returned ``redirect_url``
            lands there when the backend honours it; ignored otherwise.
    """
    token = get_access_token()
    if not token:
        return {"success": False, "message": "Not logged in. Please login first."}

    try:
        url = f"{get_server_url()}/api/v1/auth/handoff/create"
        headers = {
            "Content-Type": "application/json",
            "accept": "application/json",
            "Authorization": f"Bearer {token}",
        }
        payload = {"source": source}
        if target:
            payload["target"] = target
        response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=15)

        if response.status_code not in (200, 201):
            return {
                "success": False,
                "message": f"Failed to create handoff ticket: {response.status_code}",
            }

        data = response.json()
        redirect_url = data.get("redirect_url")
        if not redirect_url:
            ticket = data.get("ticket")
            if not ticket:
                return {"success": False, "message": "No redirect URL returned by backend."}
            redirect_url = f"{get_server_url().rstrip('/')}/auth/handoff?ticket={urllib.parse.quote(ticket)}"

        return {"success": True, "url": redirect_url}
    except Exception as e:
        logger.error(f"Failed creating dashboard handoff URL: {e}")
        return {"success": False, "message": f"Handoff setup failed: {str(e)}"}


def open_dashboard_with_handoff():
    """
    Open the web dashboard in the default browser.
    """
    from ....config.config import get_frontend_url

    target_url = f"{get_frontend_url()}/app"
    try:
        opened = webbrowser.open(target_url)
        if not opened:
            return {"success": False, "message": "Could not open browser automatically.", "url": target_url}
        return {"success": True, "message": "Dashboard opened.", "url": target_url}
    except Exception as e:
        logger.error(f"Failed opening dashboard URL in browser: {e}")
        return {"success": False, "message": f"Browser launch failed: {str(e)}", "url": target_url}
