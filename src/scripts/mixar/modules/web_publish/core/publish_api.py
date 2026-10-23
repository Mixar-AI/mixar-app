# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Client for ``/api/v1/scene-publish`` plus the presigned storage PUTs.

Backend calls go through the shared ``BaseService``/``HTTPClient`` (bearer
token, one refresh-and-retry on 401, client-version / consent / locale
headers). The service owns a dedicated client with retries OFF: ``POST
/scenes`` creates a row, so a transparent 5xx retry could double-publish.
Presigned PUTs use plain ``requests`` — S3 rejects an ``Authorization``
header next to a query-string signature. Trust and proxy are process-wide
(network contract), so no call site passes ``verify=``/``proxies=``.

Every transport failure is classified (``classify_network_error``) and
logged with its ``NET-*`` support code; HTTP failures keep the backend's
error ``code`` (``detail.data.code`` or ``data.code``) and message.

Runs on the publish worker thread; never touches ``bpy``. Construct the
service on the main thread (``HTTPClient`` reads config on creation).
"""

from __future__ import annotations

import os
import re
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote

import requests

from mixar.config.logging_config import get_logger
from mixar.modules.common.api.client import HTTPClient
from mixar.modules.common.api.constants import APIModule
from mixar.modules.common.api.exceptions import (
    AuthenticationError,
    ConnectionError as ApiConnectionError,
    HTTPClientError,
    TimeoutError as ApiTimeoutError,
)
from mixar.modules.common.api.services.base_service import BaseService
from mixar.modules.common.i18n import n_
from mixar.modules.common.network import classify_network_error, log_network_failure
from mixar.modules.web_publish.constants import API_TIMEOUT_SECONDS, UPLOAD_TIMEOUT_SECONDS

_logger = get_logger(__name__)

_THUMBNAIL_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")
# Any query string glued to a URL or a bare path ("…with url: /k?X-Amz-…").
_SIGNED_QUERY = re.compile(r"(?<=[\w/.\-])\?[^\s'\"()]+")


def redact_urls(text: str) -> str:
    """Drop every URL query string: a presigned URL's query IS the grant,
    and requests quotes the full URL in its exception text."""
    return _SIGNED_QUERY.sub("?<redacted>", str(text or ""))


def _redacted(exc: BaseException) -> BaseException:
    """The same exception type with URL-free text, for classify + logs
    (built outside the ``except`` so the original is not its context)."""
    text = redact_urls(str(exc))
    try:
        return type(exc)(text)
    except Exception:  # noqa: BLE001 — exotic constructor
        return RuntimeError(f"{exc.__class__.__name__}: {text}")


def valid_scene_id(scene_id: Any) -> str:
    """The canonical UUID string of ``scene_id``, or "" when it is not one.

    Scene ids come back from the ``.blend`` (untrusted input) and become a
    URL path segment: ``scenes/../../<other endpoint>`` would reach another
    API route with the user's token. Only a parseable UUID is ever sent."""
    if not isinstance(scene_id, str) or not scene_id.strip():
        return ""
    try:
        return str(uuid.UUID(scene_id.strip()))
    except (ValueError, TypeError, AttributeError):
        return ""


class UploadCancelled(Exception):
    """Raised from inside a presigned PUT's body read when the user cancels.

    Deliberately NOT an ``OSError``: urllib3 would wrap that into a
    connection error (classified ``NET-*`` and retried per part); a plain
    exception propagates through ``requests`` unchanged."""


class PublishApiError(Exception):
    """Structured publish failure; ``code`` mirrors backend error codes.

    ``message`` is either an untranslated client template (``params`` fill
    it) or server text passed as ``{message}`` — never translated."""

    def __init__(self, message: str, code: str = "", status_code: int = 0,
                 support_code: str = "", params: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.code = code or "publish_error"
        self.status_code = status_code
        self.support_code = support_code
        self.params = dict(params or {})


def _network_error(exc: BaseException, url: str, context: str) -> PublishApiError:
    failure = classify_network_error(exc, url)
    log_network_failure(_logger, failure, context)
    return PublishApiError("{message} ({support_code})", code="network",
                           support_code=failure.support_code,
                           params={"message": failure.message,
                                   "support_code": failure.support_code})


def _error_body(data: Any) -> Dict[str, Any]:
    """The ``{status, message, data}`` failure body, from either
    ``{"detail": {...}}`` (HTTPException) or the bare envelope."""
    if not isinstance(data, dict):
        return {}
    detail = data.get("detail")
    return detail if isinstance(detail, dict) else data


def _http_error(exc: HTTPClientError) -> PublishApiError:
    status = int(getattr(exc, "status_code", 0) or 0)
    if isinstance(exc, AuthenticationError):
        return PublishApiError(n_("Sign-in expired. Sign in again and publish."),
                               code="auth", status_code=status)
    body = _error_body(getattr(exc, "response_data", None))
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    # Moderation refusals carry ``reason`` (content_policy /
    # moderation_unavailable) instead of ``code``.
    code = str(data.get("code") or data.get("reason") or "")
    server = str(body.get("message") or getattr(exc, "message", "") or "")
    if server:
        return PublishApiError("{message}", code=code, status_code=status,
                               params={"message": server})
    return PublishApiError(n_("Request failed (HTTP {status})"), code=code,
                           status_code=status, params={"status": status})


def unwrap(payload: Any) -> Dict[str, Any]:
    """``data`` of a ``{status: "success", data}`` envelope, or the direct
    payload. A non-success envelope or a non-object body raises."""
    if not isinstance(payload, dict):
        raise PublishApiError(n_("Malformed server response"), code="malformed")
    if "status" in payload and ("data" in payload or "message" in payload):
        if payload.get("status") != "success":
            raise PublishApiError("{message}", code="server", params={
                "message": str(payload.get("message") or "Request failed")})
        data = payload.get("data")
        return data if isinstance(data, dict) else {}
    return payload


class ScenePublishService(BaseService):
    """Backend half of a publish (``/api/v1/scene-publish``)."""

    def __init__(self, client: Optional[HTTPClient] = None):
        super().__init__(client or HTTPClient(timeout=API_TIMEOUT_SECONDS, retry_count=0))

    @property
    def module(self) -> APIModule:
        return APIModule.SCENE_PUBLISH

    @property
    def base_url(self) -> str:
        return str(getattr(self._client, "_base_url", "") or "")

    @staticmethod
    def _scene_path(scene_id: str, *rest: str) -> str:
        """``scenes/<uuid>[/<rest>]``; a non-UUID id raises before any request."""
        canonical = valid_scene_id(scene_id)
        if not canonical:
            raise PublishApiError(n_("This scene has not been published yet"),
                                  code="invalid_scene_id")
        return "/".join(quote(segment, safe="") for segment in ("scenes", canonical, *rest))

    def _call(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        try:
            response = getattr(self, method)(path, **kwargs)
        except (ApiConnectionError, ApiTimeoutError) as exc:
            # HTTPClient chains the requests exception (``from e``), which
            # is what the classifier reads.
            raise _network_error(exc, self._endpoint(path), "web_publish " + path) from exc
        except HTTPClientError as exc:
            raise _http_error(exc) from exc
        except requests.exceptions.RequestException as exc:
            raise _network_error(exc, self._endpoint(path), "web_publish " + path) from exc
        return unwrap(getattr(response, "data", None))

    # -- API surface ----------------------------------------------------------

    def init_publish(self, body: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """``POST /scenes`` → ``(scene, upload_plan)``."""
        data = self._call("post", "scenes", json=body)
        return data.get("scene") or {}, data.get("upload") or {}

    def complete_upload(self, scene_id: str, upload_id: Optional[str],
                        parts: Optional[list], content_sha256: str) -> Dict[str, Any]:
        body: Dict[str, Any] = {"content_sha256": content_sha256}
        if upload_id:
            body["upload_id"] = upload_id
        if parts:
            body["parts"] = parts
        return self._call("post", self._scene_path(scene_id, "complete"),
                          json=body).get("scene") or {}

    def upload_thumbnail(self, scene_id: str, filepath: str) -> None:
        """Raw bytes; the type rides in ``?ext=`` (the shared client drops
        ``Content-Type`` whenever a body is set)."""
        ext = os.path.splitext(filepath)[1].lower() or ".png"
        if ext not in _THUMBNAIL_EXTENSIONS:
            raise PublishApiError(n_("Unsupported thumbnail type"), code="bad_thumbnail")
        with open(filepath, "rb") as handle:
            payload = handle.read()
        self._call("post", self._scene_path(scene_id, "thumbnail"), params={"ext": ext},
                   data=payload, timeout=UPLOAD_TIMEOUT_SECONDS)

    def list_scenes(self) -> List[Dict[str, Any]]:
        return list(self._call("get", "scenes").get("scenes") or [])

    def get_scene(self, scene_id: str) -> Dict[str, Any]:
        return self._call("get", self._scene_path(scene_id)).get("scene") or {}

    def update_scene(self, scene_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        return self._call("patch", self._scene_path(scene_id), json=fields).get("scene") or {}

    def delete_scene(self, scene_id: str) -> None:
        self._call("delete", self._scene_path(scene_id))

    def get_quota(self) -> Dict[str, Any]:
        return self._call("get", "quota")


# -- presigned storage --------------------------------------------------------


def put_object(url: str, filepath: str, size_bytes: int, content_type: str,
               on_progress: Optional[Callable[[int, int], None]] = None,
               should_cancel: Optional[Callable[[], bool]] = None) -> None:
    """Single presigned PUT (scenes up to the backend's simple-PUT size).
    ``should_cancel`` is polled on every body read; True raises
    ``UploadCancelled`` mid-stream."""
    with open(filepath, "rb") as handle:
        response = _put(url, _ProgressReader(handle, size_bytes, on_progress, should_cancel),
                        {"Content-Type": content_type, "Content-Length": str(size_bytes)})
    if response.status_code >= 300:
        raise PublishApiError(n_("Upload failed (HTTP {status})"), code="upload_failed",
                              status_code=response.status_code,
                              params={"status": response.status_code})


def put_part(url: str, filepath: str, offset: int, length: int,
             on_progress: Optional[Callable[[int, int], None]] = None) -> str:
    """Upload one multipart part; returns its ETag."""
    with open(filepath, "rb") as handle:
        handle.seek(offset)
        response = _put(url, _ProgressReader(handle, length, on_progress),
                        {"Content-Length": str(length)})
    if response.status_code >= 300:
        raise PublishApiError(n_("Part upload failed (HTTP {status})"), code="upload_failed",
                              status_code=response.status_code,
                              params={"status": response.status_code})
    etag = response.headers.get("ETag") or response.headers.get("etag")
    if not etag:
        raise PublishApiError(n_("Storage did not return an ETag"), code="upload_failed")
    return etag


def _put(url: str, body, headers: Dict[str, str]):
    failure = None
    try:
        return requests.put(url, data=body, headers=headers, timeout=UPLOAD_TIMEOUT_SECONDS)
    except requests.exceptions.RequestException as exc:
        failure = _redacted(exc)
    # The presigned query string is a credential: classify and log only the
    # redacted text, on the bare host, with no chained original.
    raise _network_error(failure, url.split("?", 1)[0], "web_publish storage upload")


class _ProgressReader:
    """File-like wrapper reporting read progress to a callback (and
    aborting the stream when ``should_cancel`` says so)."""

    def __init__(self, handle, total: int, on_progress=None, should_cancel=None):
        self._handle = handle
        self._remaining = total
        self._total = total
        self._on_progress = on_progress
        self._should_cancel = should_cancel

    def __len__(self) -> int:
        return self._total

    def read(self, amount: int = -1) -> bytes:
        if self._should_cancel is not None and self._should_cancel():
            raise UploadCancelled()
        if self._remaining <= 0:
            return b""
        if amount is None or amount < 0 or amount > self._remaining:
            amount = self._remaining
        chunk = self._handle.read(amount)
        self._remaining -= len(chunk)
        if self._on_progress:
            try:
                self._on_progress(self._total - max(self._remaining, 0), self._total)
            except Exception:  # noqa: BLE001 - progress must never break upload
                pass
        return chunk


def absolute_url(url: str, base_url: str = "") -> str:
    """The backend may answer with a path (``/api/v1/scene-publish/s/<slug>``,
    ``/s/<slug>`` without a viewer host): anchor it on the API host."""
    url = str(url or "")
    if url.startswith("/") and isinstance(base_url, str) and base_url:
        return base_url.rstrip("/") + url
    return url


def parse_scene_payload(scene: Dict[str, Any], base_url: str = "") -> Dict[str, Any]:
    """Normalize a backend scene payload into the fields the panel binds."""
    return {
        "id": str(scene.get("id") or ""),
        "slug": str(scene.get("slug") or ""),
        "share_url": absolute_url(scene.get("share_url"), base_url),
        "viewer_url": absolute_url(scene.get("viewer_url"), base_url),
        "revision": int(scene.get("revision") or 0),
        "status": str(scene.get("status") or ""),
    }
