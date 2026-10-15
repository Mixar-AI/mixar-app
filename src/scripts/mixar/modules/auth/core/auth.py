# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Authentication utilities for Mixar
"""

import base64
import hashlib
import json
import platform
import threading
import time
import urllib.parse
import uuid
import webbrowser

import requests

from mixar.modules.common.i18n import rpt_

from ....config.config import get_server_url
from ...common.network import classify_network_error, log_network_failure
from ....config.logging_config import get_logger
from ..utils.constants import AUTH_BASE_URL
from .device import get_device_id

logger = get_logger(__name__)

# Windows-specific credential handling to match the C++ implementation
# (creator_auth.cc): TargetName "<item>@MixarSafeStorage", which Python
# keyring's compound format would not produce.

_is_windows = platform.system() == "Windows"

if _is_windows:
    import ctypes
    from ctypes import wintypes

    # Windows Credential Manager constants
    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2

    # Use username@service format (matches Python keyring's compound format).
    # Windows keeps the original names (see ACCESS_TOKEN_ITEM below).
    WIN_TARGET_NAME_ACCESS = "AccessToken@MixarSafeStorage"
    WIN_TARGET_NAME_REFRESH = "RefreshToken@MixarSafeStorage"

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
    # keyring must not be a hard import: if it (or its platform backend
    # deps) is missing from the bundle, raising here would take down the
    # whole auth -> connection -> chat/moodboard import chain. Every call
    # site is wrapped in try/except, so a None module degrades to
    # "credentials don't persist" instead of "half the UI never registers".
    try:
        import keyring
    except ImportError as _keyring_import_error:
        keyring = None
        logger.error(
            f"keyring unavailable ({_keyring_import_error}) - "
            "credentials will not persist across sessions"
        )


# Item names (shared with the C++ shell, creator_auth.cc, which reads the
# access token before Python runs). On macOS they carry a "Mixar." prefix
# since the bundle id lost its version stamp: an item created by an older
# signing identity can be neither read nor deleted without a Keychain dialog,
# so the stable identity uses new names and never touches the old items —
# the user signs in once (there is no silent move: the old item is unreadable
# by definition). Windows (Credential Manager) and Linux (SecretService) have
# no per-app access list, so they keep the original names and an upgrade
# keeps the session; renaming there would sign every user out.
_is_macos = platform.system() == "Darwin"
ACCESS_TOKEN_ITEM = "Mixar.AccessToken" if _is_macos else "AccessToken"
REFRESH_TOKEN_ITEM = "Mixar.RefreshToken" if _is_macos else "RefreshToken"


def _read_token(item, win_target):
    """The token under its item name, or "" when absent."""
    if _is_windows:
        return _win_get_password(win_target) or ""
    # macOS: dialog-free reads (common/utils/credential_store); Linux: SecretService.
    from mixar.modules.common.utils import credential_store

    return credential_store.get_secret(item) or ""


def user_id_from_token(token):
    """The Mixar user id: the access token's ``sub`` claim (no signature
    check — this only scopes local, per-user state such as the BYOK key
    record; the server authenticates)."""
    if not token or token.count(".") != 2:
        return None
    try:
        encoded = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        sub = claims.get("sub")
        return str(sub) if sub else None
    except Exception:  # noqa: BLE001 — not a JWT
        return None


def get_access_token():
    """Get the stored access token from system credential storage."""
    try:
        return _read_token(ACCESS_TOKEN_ITEM, WIN_TARGET_NAME_ACCESS if _is_windows else None)
    except Exception as e:
        logger.warning(f"Failed to retrieve access token: {e}")
        return ""


def store_access_token(token):
    """Store the access token in system credential storage."""
    try:
        if _is_windows:
            # Use Windows Credential Manager directly with C++ compatible format
            return _win_set_password(WIN_TARGET_NAME_ACCESS, ACCESS_TOKEN_ITEM, token)
        from mixar.modules.common.utils import credential_store

        return credential_store.set_secret(ACCESS_TOKEN_ITEM, token)
    except Exception as e:
        logger.error(f"Failed to store access token: {e}")
        return False


def delete_access_token():
    """Delete the access token from system credential storage."""
    try:
        if _is_windows:
            # Use Windows Credential Manager directly with C++ compatible format
            return _win_delete_password(WIN_TARGET_NAME_ACCESS)
        from mixar.modules.common.utils import credential_store

        return credential_store.delete_secret(ACCESS_TOKEN_ITEM)
    except Exception as e:
        logger.warning(f"Failed to delete access token: {e}")
        return False


def get_refresh_token():
    """Get the stored refresh token from system credential storage."""
    try:
        return _read_token(REFRESH_TOKEN_ITEM, WIN_TARGET_NAME_REFRESH if _is_windows else None)
    except Exception as e:
        logger.warning(f"Failed to retrieve refresh token: {e}")
        return ""


def store_refresh_token(token):
    """Store the refresh token in system credential storage."""
    try:
        if _is_windows:
            # Use Windows Credential Manager directly with C++ compatible format
            return _win_set_password(WIN_TARGET_NAME_REFRESH, REFRESH_TOKEN_ITEM, token)
        from mixar.modules.common.utils import credential_store

        return credential_store.set_secret(REFRESH_TOKEN_ITEM, token)
    except Exception as e:
        logger.error(f"Failed to store refresh token: {e}")
        return False


def delete_refresh_token():
    """Delete the refresh token from system credential storage."""
    try:
        if _is_windows:
            # Use Windows Credential Manager directly with C++ compatible format
            return _win_delete_password(WIN_TARGET_NAME_REFRESH)
        from mixar.modules.common.utils import credential_store

        return credential_store.delete_secret(REFRESH_TOKEN_ITEM)
    except Exception as e:
        logger.warning(f"Failed to delete refresh token: {e}")
        return False


# Key of the pending-refresh marker inside the credential bundle
# (`common/utils/credential_store`); replaced the standalone "RefreshAttempt" item.
REFRESH_ATTEMPT_KEY = "auth:refresh_attempt"


def _refresh_token_digest(token):
    """Return a non-reversible identity for a refresh-token attempt."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# Namespace for the deterministic refresh idempotency key (any fixed UUID).
_REFRESH_IDEMPOTENCY_NAMESPACE = uuid.UUID("7b3e0c4a-6d21-5f98-9c4a-0f6a2b1d8e55")


def _refresh_idempotency_key(token):
    """A deterministic idempotency key for refreshing ``token``.

    Keyed on the refresh token so that TWO Mixar instances sharing the OS
    keychain compute the SAME key when they race to refresh the same token.
    The backend then coordinates them (``begin_refresh_token_rotation`` →
    ``wait_for_refresh_token_outcome``): one rotates, the other waits for and
    receives the same new pair, instead of the loser getting a 401 reuse and
    clearing the shared credentials (which logged both instances out). A
    UUIDv5 (SHA-1 of the namespace + token) is a valid, non-reversible key the
    backend accepts; the token cannot be recovered from it.
    """
    return str(uuid.uuid5(_REFRESH_IDEMPOTENCY_NAMESPACE, token))


def _load_persisted_refresh_attempt():
    """Return ``(storage_available, attempt_or_none)`` from safe storage.

    ``storage_available`` is False only when safe storage itself cannot be
    read (or an invalid marker cannot be removed). A marker whose *content*
    is invalid is discarded and reported as absent: its idempotency key is
    unrecoverable, so the only safe way forward is a fresh logical attempt.
    At worst the backend rejects that attempt as a definitive replay and the
    user re-authenticates once — instead of refresh being wedged forever.
    """
    # The marker lives in the credential bundle (one Keychain item for every
    # Python-owned secret, read once per process); an older build's own
    # "RefreshAttempt" item is moved in on first use.
    from mixar.modules.common.utils import credential_store

    try:
        credential_store.migrate_legacy_entry(
            "RefreshAttempt", REFRESH_ATTEMPT_KEY, parse=json.loads)
        if not credential_store.store_available():
            logger.error("Failed to read pending refresh attempt: store unavailable")
            return False, None
        parsed = credential_store.get_value(REFRESH_ATTEMPT_KEY)
    except Exception as e:
        logger.error(f"Failed to read pending refresh attempt: {e}")
        return False, None
    if not parsed:
        return True, None

    attempt = None
    try:
        digest = parsed.get("refresh_token_digest")
        idempotency_key = parsed.get("idempotency_key")
        parsed_key = uuid.UUID(idempotency_key)
        if (
            isinstance(digest, str)
            and isinstance(idempotency_key, str)
            and len(digest) == 64
            and int(digest, 16) >= 0
            and parsed_key.version in (4, 5)
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
    from mixar.modules.common.utils import credential_store

    try:
        return credential_store.set_value(REFRESH_ATTEMPT_KEY, {
            "refresh_token_digest": attempt["refresh_token_digest"],
            "idempotency_key": attempt["idempotency_key"],
        })
    except Exception as e:
        logger.error(f"Failed to persist pending refresh attempt: {e}")
        return False


def _delete_persisted_refresh_attempt():
    """Delete the durable logical-attempt marker; absence is success."""
    from mixar.modules.common.utils import credential_store

    try:
        return credential_store.delete_value(REFRESH_ATTEMPT_KEY)
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
                        "message": rpt_("Login successful"),
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
                    "message": rpt_("Incomplete token pair in login response"),
                }
        else:
            # Parse error message from response
            error_message = rpt_("Authentication failed: {status}").format(
                status=response.status_code)
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

    except requests.exceptions.RequestException as e:
        failure = classify_network_error(e, url=url)
        log_network_failure(logger, failure, "Login")
        return {
            "success": False,
            "message": failure.user_text,
            "failure_kind": failure.kind,
        }
    except Exception as e:
        return {
            "success": False,
            "message": rpt_("Login error: {error}").format(error=e),
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
            # Replay the marker's OWN key, never a recomputed one. This branch
            # recovers an ambiguous (lost-response) attempt, whose whole purpose
            # is to resend the identical Idempotency-Key so the backend returns
            # the same outcome instead of reading a rotated token as reuse. A
            # fresh attempt already computes the deterministic key, so two new
            # instances still converge; recomputing here would instead send a
            # different key for a marker an older build wrote (random uuid4) and
            # force a logout across the upgrade boundary.
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
            # Deterministic per token so a second instance racing on the same
            # token sends the same key and the backend coordinates them.
            "idempotency_key": _refresh_idempotency_key(refresh_token),
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
        return False, rpt_("Failed to store refresh token")
    if not store_access_token(new_access_token):
        _restore_token_pair(old_access_token, old_refresh_token)
        return False, rpt_("Failed to store access token")
    return True, None


# The refresh token the last explicit login replaced. Captured under the
# refresh fence so a rotation can never slip between "login stored" and
# "guest claimed" (guest.sign_in): it is the guest's proof of possession.
_replaced_refresh_token = ""


def take_replaced_refresh_token():
    """Return (and forget) the refresh token the last login replaced."""
    global _replaced_refresh_token
    with _refresh_lock:
        token, _replaced_refresh_token = _replaced_refresh_token, ""
        return token


def store_login_token_pair(access_token, refresh_token):
    """Atomically fence an explicit login pair against refresh operations."""
    global _replaced_refresh_token
    with _refresh_lock:
        _, previous_refresh_token = _credentials_snapshot()
        stored, error = _replace_token_pair_locked(access_token, refresh_token)
        if stored:
            _replaced_refresh_token = previous_refresh_token
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

    except requests.exceptions.RequestException as e:
        # Transport failure: the refresh token was not consumed, keep the
        # attempt so the same idempotency key is replayed later.
        failure = classify_network_error(e, url=url)
        log_network_failure(logger, failure, "Token refresh")
        return ({
            "success": False,
            "message": failure.user_text,
            "failure_kind": failure.kind,
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
            "name": "",
            "credits": 0,
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
            # Optional on the backend (most SSO signups never set one) —
            # the profile card falls back to the email's local part.
            response_data["data"]["name"] = user_data.get("name") or ""
            response_data["data"]["credits"] = user_data.get("credits", 0)
            # A guest account (no sign-in yet); the UI shows "Guest", not the
            # placeholder email, and every paid route answers 403.
            response_data["data"]["is_guest"] = bool(user_data.get("is_guest", False))
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

    except requests.exceptions.RequestException as e:
        failure = classify_network_error(e, url=url)
        log_network_failure(logger, failure, "User info")
        response_data["status"] = "failure"
        response_data["message"] = failure.user_text
        response_data["failure_kind"] = failure.kind
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
        return {"success": False, "message": rpt_("Not logged in. Please login first.")}

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
                "message": rpt_("Failed to create handoff ticket: {status}").format(
                    status=response.status_code),
            }

        data = response.json()
        redirect_url = data.get("redirect_url")
        if not redirect_url:
            ticket = data.get("ticket")
            if not ticket:
                return {"success": False, "message": rpt_("No redirect URL returned by backend.")}
            redirect_url = f"{get_server_url().rstrip('/')}/auth/handoff?ticket={urllib.parse.quote(ticket)}"

        return {"success": True, "url": redirect_url}
    except Exception as e:
        logger.error(f"Failed creating dashboard handoff URL: {e}")
        return {"success": False, "message": rpt_("Handoff setup failed: {error}").format(error=e)}


def open_dashboard_with_handoff():
    """
    Open the web dashboard in the default browser.
    """
    from ....config.config import get_frontend_url

    target_url = f"{get_frontend_url()}/app"
    try:
        opened = webbrowser.open(target_url)
        if not opened:
            return {"success": False, "message": rpt_("Could not open browser automatically."),
                    "url": target_url}
        return {"success": True, "message": rpt_("Dashboard opened."), "url": target_url}
    except Exception as e:
        logger.error(f"Failed opening dashboard URL in browser: {e}")
        return {"success": False, "message": rpt_("Browser launch failed: {error}").format(error=e),
                "url": target_url}
