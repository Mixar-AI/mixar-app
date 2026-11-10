# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Remix endpoints of the Mixar Store — worker threads only.

Shares the store client's auth, refresh and error handling. The source is
fetched from a signed URL without the bearer, and checked against the
store's record (size always, sha256 when the store has one).
"""

from __future__ import annotations

import hashlib
from urllib.parse import quote, urlsplit

import requests

from mixar.modules.game_studio.constants import UPLOAD_CHUNK, UPLOAD_TIMEOUT_S
from mixar.modules.game_studio.core.store_client import (StoreClient, StoreError, _network_error,
                                                         _remove)


LOOPBACK = ("127.0.0.1", "localhost", "::1")


class RemixClient(StoreClient):
    def pending(self) -> list[dict]:
        data = self.request("GET", "api/v1/remix/intents/pending") or {}
        items = data.get("items") if isinstance(data, dict) else None
        return [item for item in items or () if isinstance(item, dict) and item.get("intent_id")]

    def claim(self, intent_id: str) -> dict:
        return self.request("POST", f"api/v1/remix/intents/{quote(str(intent_id), safe='')}/claim") or {}

    def source(self, kind: str, ref: str) -> dict:
        if kind not in ("post", "game"):
            raise StoreError("Unknown kind of remix.", "bad_request")
        return self.request("GET", f"api/v1/remix/{kind}/{quote(str(ref), safe='')}/source") or {}

    def fetch_source(self, url: str, path: str, size_bytes: int = 0, sha256: str = "",
                     on_progress=None, cancel=None) -> str:
        # The file is opened as a project, so it is held to the store's
        # record: a size is always required, a sha256 whenever the store has
        # one, and the link must be https (plain http only to this machine).
        if not size_bytes or int(size_bytes) <= 0:
            raise StoreError("The store did not say how big the project is; nothing was downloaded.",
                             "bad_response")
        parts = urlsplit(str(url))
        if parts.scheme != "https" and not (parts.scheme == "http" and parts.hostname in LOOPBACK):
            raise StoreError("The store sent a download link Mixar won't follow.", "bad_response")
        digest, size = hashlib.sha256(), 0
        try:
            response = requests.get(url, stream=True, timeout=UPLOAD_TIMEOUT_S)
        except requests.exceptions.RequestException as exc:
            raise _network_error(exc, url, "Remix download") from exc
        try:
            if not response.ok:
                raise StoreError(f"The download was refused ({response.status_code}).",
                                 "download_failed", response.status_code)
            with open(path, "wb") as handle:
                for chunk in response.iter_content(UPLOAD_CHUNK):
                    if cancel is not None and cancel.is_set():
                        raise StoreError("Cancelled.", "cancelled")
                    digest.update(chunk)
                    size += len(chunk)
                    if size_bytes and size > size_bytes:
                        raise StoreError("The download is larger than the store's record.",
                                         "size_mismatch")
                    handle.write(chunk)
                    if on_progress is not None and size_bytes:
                        on_progress(min(1.0, size / size_bytes))
        except requests.exceptions.RequestException as exc:
            _remove(path)
            raise _network_error(exc, url, "Remix download") from exc
        except BaseException:
            _remove(path)
            raise
        finally:
            response.close()
        if size_bytes and size != size_bytes:
            _remove(path)
            raise StoreError("The download is not the size the store recorded.", "size_mismatch")
        if sha256 and digest.hexdigest() != sha256.lower():
            _remove(path)
            raise StoreError("The download does not match the store's record; nothing was opened.",
                             "sha256_mismatch")
        return digest.hexdigest()
