# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Authentication utilities for Mixar
"""

import json
import platform
import threading
import time
import urllib.parse
import webbrowser

import requests

from ....config.config import get_server_url
from ....config.logging_config import get_logger
from ..utils.constants import AUTH_BASE_URL

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
        data = urllib.parse.urlencode({
            "username": username,
            "password": password,
        })

        response = requests.post(url, headers=headers, data=data, timeout=30)

        if response.status_code == 200:
            response_data = response.json()
            access_token = response_data.get("access_token")
            refresh_token = response_data.get("refresh_token")
            if access_token and access_token.strip():
                access_stored = store_access_token(access_token)
                refresh_stored = True
                if refresh_token and refresh_token.strip():
                    refresh_stored = store_refresh_token(refresh_token)

                if access_stored:
                    if not refresh_stored:
                        logger.warning("Access token stored but refresh token storage failed")
                    logger.info("Login successful")
                    return {
                        "success": True,
                        "message": "Login successful",
                        "token": access_token,
                    }
                else:
                    return {
                        "success": False,
                        "message": "Failed to store access token",
                    }
            else:
                return {
                    "success": False,
                    "message": "No access token in response",
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
# hitting 401 at the same expiry instant) must therefore be single-flighted —
# a second in-flight refresh would send the now-invalidated old token, get
# 401, and delete the freshly stored credentials, silently logging the user
# out. Threads that arrive while/just after a refresh completes reuse its
# result instead of rotating again.
_refresh_lock = threading.Lock()
_last_refresh_success = None  # (time.monotonic(), result dict)
_REFRESH_REUSE_WINDOW = 10.0  # seconds


def refresh_access_token():
    """
    Refresh the access token using the stored refresh token.

    Thread-safe and single-flighted: concurrent callers are serialized, and
    callers that arrive within a short window of a successful refresh get the
    already-refreshed token back instead of triggering another rotation.

    Returns dict with:
        - success: bool
        - message: str
        - token: str (new access token, only if success)
    """
    global _last_refresh_success
    with _refresh_lock:
        if _last_refresh_success is not None:
            age = time.monotonic() - _last_refresh_success[0]
            if 0 <= age < _REFRESH_REUSE_WINDOW:
                return _last_refresh_success[1]
        result = _refresh_access_token_locked()
        if result.get("success"):
            _last_refresh_success = (time.monotonic(), result)
        return result


def _refresh_access_token_locked():
    """Perform the actual refresh request. Caller must hold ``_refresh_lock``."""
    refresh_token = get_refresh_token()
    if not refresh_token:
        return {
            "success": False,
            "message": "No refresh token available",
        }

    try:
        url = f"{get_server_url()}/api/v1/auth/refresh"
        headers = {
            "Content-Type": "application/json",
            "accept": "application/json",
        }
        data = json.dumps({"refresh_token": refresh_token})

        response = requests.post(url, headers=headers, data=data, timeout=30)

        if response.status_code == 200:
            response_data = response.json()
            new_access_token = response_data.get("access_token")
            new_refresh_token = response_data.get("refresh_token")

            if new_access_token and new_access_token.strip():
                if not store_access_token(new_access_token):
                    return {
                        "success": False,
                        "message": "Failed to store new access token",
                    }
                if new_refresh_token and new_refresh_token.strip():
                    if not store_refresh_token(new_refresh_token):
                        logger.warning("Failed to store new refresh token")
                logger.info("Token refreshed successfully")
                return {
                    "success": True,
                    "message": "Token refreshed successfully",
                    "token": new_access_token,
                }
            else:
                return {
                    "success": False,
                    "message": "No access token in refresh response",
                }
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
                # Tokens are invalid - delete them
                logger.warning(f"Token refresh failed with {response.status_code}: {error_message}")
                delete_access_token()
                delete_refresh_token()
            else:
                # Other error (4xx, 5xx) - keep tokens for retry
                logger.warning(f"Token refresh failed: {error_message}")
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
            "message": f"Token refresh error: {str(e)}",
        }


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


def create_dashboard_handoff_url():
    """
    Create a one-time auth handoff URL for the web dashboard.
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
        payload = {"source": "texture_painting"}
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
