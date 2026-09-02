# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""REST client for the scene_publish backend surface.

Runs on the publish worker thread (never the main thread). Uses the shared
auth module for token injection with a single refresh-and-retry on 401, and
plain requests for the presigned S3 uploads (no auth header — the signature
carries the grant).
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple

import requests

from mixar.config.logging_config import get_logger
from mixar.modules.web_publish.constants import (
    API_BASE_PATH,
    API_TIMEOUT_SECONDS,
    UPLOAD_TIMEOUT_SECONDS,
)

# NOTE: auth (keyring/OAuth) and config (bpy) are imported LAZILY inside the
# call sites below — this module loads in test/dev contexts where neither is
# available, and the publish client only runs on the worker thread at runtime.

_logger = get_logger(__name__)


class PublishApiError(Exception):
    """Structured publish failure; ``code`` mirrors backend error codes."""

    def __init__(self, message: str, code: str = "", status_code: int = 0):
        super().__init__(message)
        self.message = message
        self.code = code or "publish_error"
        self.status_code = status_code


class ScenePublishClient:
    def __init__(self, server_url: Optional[str] = None):
        self._server_url = server_url  # None → resolve lazily (tests inject)

    # -- plumbing ------------------------------------------------------------

    def _base(self) -> str:
        if self._server_url:
            return self._server_url.rstrip("/")
        from mixar.config.config import get_server_url

        return get_server_url().rstrip("/")

    @staticmethod
    def _auth():
        from mixar.modules.auth.core.auth import get_access_token

        return get_access_token()

    @staticmethod
    def _refresh_auth():
        from mixar.modules.auth.core.auth import refresh_access_token

        refresh_access_token()

    def _headers(self) -> Dict[str, str]:
        token = self._auth()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
        data=None,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = API_TIMEOUT_SECONDS,
    ) -> Dict[str, Any]:
        url = f"{self._base()}/{API_BASE_PATH}/{path.lstrip('/')}"
        merged = self._headers()
        if headers:
            merged.update(headers)
        if data is not None:
            merged.pop("Content-Type", None)

        response = requests.request(
            method, url, json=json_body, data=data, headers=merged, timeout=timeout
        )
        if response.status_code == 401:
            # One token refresh + retry; a second 401 is terminal.
            try:
                self._refresh_auth()
            except Exception as exc:  # noqa: BLE001 - refresh best-effort
                _logger.warning(f"web_publish token refresh failed: {exc}")
                raise PublishApiError(
                    "Sign in expired. Please sign in and publish again.",
                    code="auth",
                    status_code=401,
                )
            merged = self._headers()
            if headers:
                merged.update({k: v for k, v in headers.items() if k != "Authorization"})
            if data is not None:
                merged.pop("Content-Type", None)
            response = requests.request(
                method, url, json=json_body, data=data, headers=merged, timeout=timeout
            )

        return self._parse(response)

    @staticmethod
    def _parse(response: requests.Response) -> Dict[str, Any]:
        try:
            payload = response.json()
        except ValueError:
            payload = None

        if response.status_code >= 400:
            code = ""
            message = f"Request failed ({response.status_code})"
            if isinstance(payload, dict):
                code = str(payload.get("data", {}).get("code", "") or "")
                message = str(payload.get("message") or message)
            raise PublishApiError(message, code=code, status_code=response.status_code)

        if not isinstance(payload, dict):
            raise PublishApiError("Malformed server response", code="malformed")
        if payload.get("status") != "success":
            raise PublishApiError(
                str(payload.get("message") or "Request failed"), code="server"
            )
        return payload

    # -- API surface ----------------------------------------------------------

    def init_publish(self, body: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """POST /scenes → ({scene...}, {upload plan...}) from ``data``."""
        payload = self._request("POST", "scenes", json_body=body)
        data = payload.get("data") or {}
        return data.get("scene") or {}, data.get("upload") or {}

    def complete_upload(
        self,
        scene_id: str,
        upload_id: Optional[str],
        parts: Optional[list],
        content_sha256: str,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {"content_sha256": content_sha256}
        if upload_id:
            body["upload_id"] = upload_id
        if parts:
            body["parts"] = parts
        payload = self._request("POST", f"scenes/{scene_id}/complete", json_body=body)
        return payload.get("data", {}).get("scene") or {}

    def upload_thumbnail(self, scene_id: str, filepath: str) -> None:
        with open(filepath, "rb") as handle:
            self._request(
                "POST",
                f"scenes/{scene_id}/thumbnail",
                data=handle,
                headers={"Content-Type": "image/png"},
                timeout=UPLOAD_TIMEOUT_SECONDS,
            )

    def get_my_scenes(self) -> list:
        payload = self._request("GET", "scenes")
        return payload.get("data", {}).get("scenes") or []

    def delete_scene(self, scene_id: str) -> None:
        self._request("DELETE", f"scenes/{scene_id}")

    def get_quota(self) -> Dict[str, Any]:
        payload = self._request("GET", "quota")
        return payload.get("data") or {}

    # -- presigned storage ----------------------------------------------------

    def put_object(self, url: str, filepath: str, size_bytes: int, content_type: str,
                   on_progress=None) -> None:
        """Single presigned PUT (small scenes)."""
        with open(filepath, "rb") as handle:
            response = requests.put(
                url,
                data=_ProgressReader(handle, size_bytes, on_progress),
                headers={"Content-Type": content_type, "Content-Length": str(size_bytes)},
                timeout=UPLOAD_TIMEOUT_SECONDS,
            )
        if response.status_code >= 300:
            raise PublishApiError(
                f"Upload failed ({response.status_code})", code="upload_failed"
            )

    def put_part(self, url: str, filepath: str, offset: int, length: int,
                 on_progress=None) -> str:
        """Upload one multipart part; returns its ETag."""
        with open(filepath, "rb") as handle:
            handle.seek(offset)
            response = requests.put(
                url,
                data=_ProgressReader(handle, length, on_progress),
                headers={"Content-Length": str(length)},
                timeout=UPLOAD_TIMEOUT_SECONDS,
            )
        if response.status_code >= 300:
            raise PublishApiError(
                f"Part upload failed ({response.status_code})", code="upload_failed"
            )
        etag = response.headers.get("ETag") or response.headers.get("etag")
        if not etag:
            raise PublishApiError("Storage did not return an ETag", code="upload_failed")
        return etag


class _ProgressReader:
    """File-like wrapper reporting read progress to a callback."""

    def __init__(self, handle, total: int, on_progress=None):
        self._handle = handle
        self._remaining = total
        self._total = total
        self._on_progress = on_progress

    def read(self, amount: int = -1) -> bytes:
        chunk = self._handle.read(amount)
        self._remaining -= len(chunk)
        if self._on_progress:
            try:
                self._on_progress(self._total - max(self._remaining, 0), self._total)
            except Exception:  # noqa: BLE001 - progress must never break upload
                pass
        return chunk


def parse_scene_payload(scene: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a backend scene payload into the fields the panel binds."""
    return {
        "id": str(scene.get("id") or ""),
        "slug": str(scene.get("slug") or ""),
        "share_url": str(scene.get("share_url") or ""),
        "viewer_url": str(scene.get("viewer_url") or ""),
        "revision": int(scene.get("revision") or 0),
        "status": str(scene.get("status") or ""),
    }


def encode_body(body: Dict[str, Any]) -> bytes:
    return json.dumps(body).encode("utf-8")
