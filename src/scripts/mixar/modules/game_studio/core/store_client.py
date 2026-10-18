# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mixar Store client (contract §4) — worker threads only.

Authenticated with the user's Mixar bearer token (read from the credential
store HERE, on the worker: a Keychain read never runs on the main thread).
Trust and proxy are process-wide (startup phase 2), so nothing here sets
``verify=``/``proxies=``. Transport failures go through
``classify_network_error``; HTTP errors surface the store's
``detail={code, message}``. The presigned build upload is a plain PUT with
ONLY the presign's headers — the bearer never reaches object storage.
"""

from __future__ import annotations

import hashlib
import os

import requests

from mixar.config.logging_config import get_logger

from ..constants import STORE_TIMEOUT_S, UPLOAD_CHUNK, UPLOAD_TIMEOUT_S

logger = get_logger(__name__)


class StoreError(Exception):
    def __init__(self, message: str, code: str = "store_error", status: int = 0, detail=None):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status
        self.detail = dict(detail or {})  # the store's extra fields (e.g. game_id)


def sha256_file(path: str, cancel=None) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    with open(path, "rb") as handle:
        while True:
            if cancel is not None and cancel.is_set():
                raise StoreError("Cancelled.", "cancelled")
            chunk = handle.read(UPLOAD_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


class _ProgressFile:
    """File body with a length (so requests sends Content-Length, which a
    presigned PUT requires — never chunked) that reports bytes read."""

    def __init__(self, path: str, on_progress=None, cancel=None):
        self._handle = open(path, "rb")
        self._size = os.path.getsize(path)
        self._sent = 0
        self._on_progress = on_progress
        self._cancel = cancel

    def __len__(self):
        return self._size

    def read(self, amount=-1):
        if self._cancel is not None and self._cancel.is_set():
            raise StoreError("Cancelled.", "cancelled")
        chunk = self._handle.read(UPLOAD_CHUNK if amount is None or amount < 0 else amount)
        self._sent += len(chunk)
        if self._on_progress is not None and self._size:
            self._on_progress(self._sent / self._size)
        return chunk

    def close(self):
        self._handle.close()


def _default_token() -> str:
    from mixar.modules.auth.core.auth import get_access_token
    return get_access_token() or ""


def _default_refresh() -> bool:
    try:
        from mixar.modules.auth.core.auth import refresh_access_token
        return bool((refresh_access_token() or {}).get("success"))
    except Exception:
        return False


def _client_headers() -> dict:
    headers = {}
    try:
        from mixar.modules.common.api.client_version import client_version_headers
        headers.update(client_version_headers())
    except Exception:
        pass
    try:
        from mixar.modules.common.i18n import ui_locale
        headers["X-Mixar-Locale"] = ui_locale()
    except Exception:
        pass
    return headers


def _network_error(exc: BaseException, url: str, context: str) -> StoreError:
    from mixar.modules.common.network import classify_network_error, log_network_failure
    failure = classify_network_error(exc, url)
    log_network_failure(logger, failure, context)
    return StoreError(failure.user_text, failure.support_code)


def _http_error(response) -> StoreError:
    code, message, extra = f"http_{response.status_code}", "", {}
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, dict):
            code = str(detail.get("code") or code)
            message = str(detail.get("message") or "")
            extra = {k: v for k, v in detail.items() if k not in ("code", "message")}
        elif isinstance(detail, list):  # FastAPI request validation (422)
            code = "invalid_request"
            message = "; ".join(str(item.get("msg") or "") for item in detail
                                if isinstance(item, dict))[:300]
        elif isinstance(detail, str):
            message = detail
        message = message or str(body.get("message") or "")
        data = body.get("data")
        if isinstance(data, dict) and data.get("game_id"):  # slug_taken on the caller's own game
            extra.setdefault("game_id", data["game_id"])
    if response.status_code == 401:
        code, message = "login_required", message or "Sign in to Mixar to publish."
    return StoreError(message or f"The store answered {response.status_code}.", code,
                      response.status_code, extra)


class StoreClient:
    def __init__(self, api_base: str, token_provider=None, refresh=None, session=None):
        self.api_base = str(api_base or "").rstrip("/")
        self._token = token_provider or _default_token
        self._refresh = refresh or _default_refresh
        self._session = session or requests.Session()

    def _headers(self) -> dict:
        headers = {"Accept": "application/json", **_client_headers()}
        token = self._token()
        if not token:
            raise StoreError("Sign in to Mixar to publish.", "login_required", 401)
        headers["Authorization"] = f"Bearer {token}"
        return headers

    def request(self, method: str, path: str, body=None, timeout=STORE_TIMEOUT_S):
        """The envelope's ``data`` (or the raw JSON body without one)."""
        url = f"{self.api_base}/{path.lstrip('/')}"
        for attempt in (0, 1):
            try:
                response = self._session.request(method, url, json=body, headers=self._headers(),
                                                 timeout=timeout)
            except requests.exceptions.RequestException as exc:
                raise _network_error(exc, url, f"Store {method} {path}") from exc
            if response.status_code == 401 and attempt == 0 and self._refresh():
                continue
            break
        if not response.ok:
            raise _http_error(response)
        try:
            payload = response.json()
        except ValueError as exc:
            raise StoreError("The store sent an unreadable answer.", "bad_response",
                             response.status_code) from exc
        if isinstance(payload, dict) and "data" in payload and "status" in payload:
            return payload["data"]
        return payload

    # --- §4 endpoints -----------------------------------------------------------
    def create_game(self, fields: dict) -> dict:
        data = self.request("POST", "api/v1/games", {**fields, "source": "mixar"})
        return (data or {}).get("game", data) or {}

    def update_game(self, game_id: str, fields: dict) -> dict:
        data = self.request("PATCH", f"api/v1/games/{game_id}", fields)
        return (data or {}).get("game", data) or {}

    def get_game(self, game_id: str) -> dict:
        data = self.request("GET", f"api/v1/games/{game_id}")
        return (data or {}).get("game", data) or {}

    def create_build(self, game_id: str, platform: str, version: str, filename: str,
                     size_bytes: int, sha256: str) -> dict:
        return self.request("POST", f"api/v1/games/{game_id}/builds", {
            "platform": platform, "version": version, "filename": filename,
            "size_bytes": int(size_bytes), "sha256": sha256}) or {}

    def complete_build(self, game_id: str, build_id: str) -> dict:
        return self.request("POST", f"api/v1/games/{game_id}/builds/{build_id}/complete") or {}

    def create_media(self, game_id: str, kind: str, filename: str, size_bytes: int,
                     sha256: str) -> dict:
        return self.request("POST", f"api/v1/games/{game_id}/media", {
            "kind": kind, "filename": filename, "size_bytes": int(size_bytes),
            "sha256": sha256}) or {}

    def complete_media(self, game_id: str, upload_id: str) -> dict:
        return self.request("POST", f"api/v1/games/{game_id}/media/{upload_id}/complete") or {}

    def publish(self, game_id: str) -> dict:
        data = self.request("POST", f"api/v1/games/{game_id}/publish")
        return (data or {}).get("game", data) or {}

    def upload(self, put_url: str, headers: dict, path: str, on_progress=None, cancel=None) -> None:
        """Signed PUT (media and builds, ~15 min): exactly the returned
        headers, never the bearer."""
        body = _ProgressFile(path, on_progress, cancel)
        try:
            response = requests.put(put_url, data=body, headers=dict(headers or {}),
                                    timeout=UPLOAD_TIMEOUT_S)
        except requests.exceptions.RequestException as exc:
            if cancel is not None and cancel.is_set():
                raise StoreError("Cancelled.", "cancelled") from exc
            raise _network_error(exc, put_url, "Store build upload") from exc
        finally:
            body.close()
        if not response.ok:
            raise StoreError(f"The build upload was refused ({response.status_code}).",
                             "upload_failed", response.status_code)
