# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mixar Community client: upload a file and create or update a draft post.

Mixar Community is a separate service (its own API origin) that trusts the
same Mixar account, so calls carry the user's normal bearer token through a
dedicated HTTPClient. The file bytes go to the upload URL the community API
returns: a presigned storage URL gets NO Authorization header (S3 refuses
requests carrying two auth schemes); only the community API's own origin does.

Runs on a worker thread: no bpy in here.
"""

import hashlib
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlsplit

import requests

from mixar.config.config import get_community_api_url, get_community_url
from mixar.config.logging_config import get_logger
from mixar.modules.common.network.core.errors import classify_network_error, log_network_failure

from mixar.modules.auth.core.auth import get_access_token
from ..client import HTTPClient

logger = get_logger(__name__)

UPLOAD_TIMEOUT_S = 300


class CommunityError(Exception):
    """A user-facing failure; ``str(exc)`` is safe to show in a toast."""

    def __init__(self, message: str, code: str = "error"):
        super().__init__(message)
        self.code = code


@dataclass
class PublishResult:
    post_id: str
    web_url: str
    created: bool


class CommunityService:
    def __init__(self, api_url: Optional[str] = None, web_url: Optional[str] = None, http=None):
        self.api_url = (api_url or get_community_api_url()).rstrip("/")
        self.web_url = (web_url or get_community_url()).rstrip("/")
        self._http = http or HTTPClient(base_url=self.api_url)

    # -- plumbing ---------------------------------------------------------

    def _call(self, method: str, endpoint: str, **kwargs) -> dict:
        try:
            response = self._http.request(method, endpoint, raise_for_status=False, **kwargs)
        except Exception as exc:
            failure = classify_network_error(exc, f"{self.api_url}/{endpoint}")
            log_network_failure(logger, failure, "community")
            raise CommunityError(failure.user_text, failure.kind) from exc
        body = response.data if isinstance(response.data, dict) else {}
        if not response.success:
            data = body.get("data") if isinstance(body.get("data"), dict) else {}
            if response.status_code == 401:
                raise CommunityError("Sign in to Mixar again, then publish", "not_authenticated")
            raise CommunityError(body.get("message") or f"Mixar Community returned {response.status_code}",
                                 data.get("code") or "error")
        return body.get("data") or {}

    def _put_bytes(self, target: dict, data: bytes) -> None:
        url = target["url"]
        headers = dict(target.get("headers") or {})
        # Local/dev storage uploads back to the community API itself, which
        # needs the bearer; third-party storage URLs must not get it.
        if urlsplit(url).netloc == urlsplit(self.api_url).netloc:
            token = get_access_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"
        try:
            response = requests.request(target.get("method", "PUT"), url, data=data,
                                        headers=headers, timeout=UPLOAD_TIMEOUT_S)
        except requests.exceptions.RequestException as exc:
            failure = classify_network_error(exc, url)
            log_network_failure(logger, failure, "community upload")
            raise CommunityError(failure.user_text, failure.kind) from exc
        if not response.ok:
            raise CommunityError(f"Upload failed ({response.status_code}); try again", "upload_failed")

    # -- operations -------------------------------------------------------

    def upload(self, filename: str, data: bytes, *, role: str, kind: Optional[str] = None) -> str:
        declared = self._call("POST", "uploads", json={
            "filename": filename,
            "size_bytes": len(data),
            "role": role,
            "kind": kind,
            "sha256": hashlib.sha256(data).hexdigest(),
        })
        self._put_bytes(declared["upload"], data)
        self._call("POST", f"uploads/{declared['file']['id']}/complete")
        return declared["file"]["id"]

    def ensure_profile(self) -> None:
        me = self._call("GET", "profiles/me")
        if not me.get("profile"):
            raise CommunityError(
                f"Claim your Mixar Community handle first at {self.web_url}/settings/profile",
                "profile_required",
            )

    def publish_addon(self, filename: str, data: bytes, *, title: str, description: str,
                      existing_post_id: Optional[str] = None) -> PublishResult:
        """Upload the add-on and attach it to a post: a new draft, or the author's existing post.

        Updating replaces only the post's previous add-on zip; the new version goes back to
        moderator review, so buyers never receive an unreviewed update.
        """
        self.ensure_profile()
        file_id = self.upload(filename, data, role="download", kind="addon")

        if existing_post_id:
            try:
                post = self._call("GET", f"posts/{existing_post_id}")
            except CommunityError as exc:
                if exc.code != "not_found":
                    raise
                post = None
            if post and post.get("viewer", {}).get("is_owner"):
                keep = [f["id"] for f in post.get("previews", [])]
                keep += [f["id"] for f in post.get("downloads", []) if f.get("kind") != "addon"]
                self._call("PATCH", f"posts/{existing_post_id}", json={"file_ids": keep + [file_id]})
                return PublishResult(existing_post_id, f"{self.web_url}/p/{existing_post_id}", created=False)

        post = self._call("POST", "posts", json={
            "kind": "addon",
            "title": title[:140],
            "description": description[:10000],
            "tags": ["addon", "mixar-agent"],
            "visibility": "public",
            "file_ids": [file_id],
            "made_with": {"tools": ["Mixar", "Mixar agent"], "models": [], "prompt": None},
        })
        # Left as a draft: price, license and publishing are chosen on the web page we open.
        return PublishResult(post["id"], f"{self.web_url}/p/{post['id']}", created=True)
