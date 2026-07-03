# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Download manifest assets (PBR maps, masks) into temp files and bpy.data.images."""

import hashlib
import os
import time
import tempfile
import urllib.parse
import urllib.request
from urllib.error import HTTPError, URLError

import bpy

# Manifests are authored by the AI backend and can be influenced by user
# prompts. Restrict downloads to remote http(s) assets so URLs such as
# file:///home/user/.env cannot read local files into bpy.data.images.
_ALLOWED_SCHEMES = ("http", "https")
_RETRYABLE_HTTP_STATUS = {408, 429, 500, 502, 503, 504}
_DEFAULT_ATTEMPTS = 3
_DEFAULT_BACKOFF_SECONDS = 0.35


def _filename_for_url(url: str) -> str:
    base = url.split("?", 1)[0].rsplit("/", 1)[-1] or "asset"
    if "." not in base:
        base += ".png"
    digest = hashlib.sha1(url.encode()).hexdigest()[:8]
    stem, ext = os.path.splitext(base)
    return f"{stem}_{digest}{ext}"


def _is_retryable_error(exc: BaseException) -> bool:
    if isinstance(exc, HTTPError):
        return exc.code in _RETRYABLE_HTTP_STATUS
    if isinstance(exc, (URLError, TimeoutError, ConnectionError, OSError)):
        return True
    return False


def _read_url(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "MixarTexturePainting/1.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        return resp.read()


def download_to_tempfile(
    url: str,
    dest_dir: str = None,
    timeout: float = 30.0,
    attempts: int = _DEFAULT_ATTEMPTS,
    backoff_seconds: float = _DEFAULT_BACKOFF_SECONDS,
) -> str:
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise ValueError(
            f"Refusing to download asset from non-http(s) URL (scheme={scheme!r}): {url!r}"
        )
    dest_dir = dest_dir or os.path.join(tempfile.gettempdir(), "mixar_layered_build")
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, _filename_for_url(url))
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path

    attempts = max(1, int(attempts or 1))
    last_error = None
    for attempt in range(1, attempts + 1):
        tmp_path = f"{path}.part"
        try:
            data = _read_url(url, timeout)
            with open(tmp_path, "wb") as f:
                f.write(data)
            os.replace(tmp_path, path)
            return path
        except Exception as exc:
            last_error = exc
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
            if attempt >= attempts or not _is_retryable_error(exc):
                break
            time.sleep(backoff_seconds * attempt)
    raise last_error


def load_image(url: str, non_color: bool) -> "bpy.types.Image":
    """Download url and load as a bpy image, setting colorspace."""
    path = download_to_tempfile(url)
    img = bpy.data.images.load(path, check_existing=True)
    try:
        img.colorspace_settings.name = "Non-Color" if non_color else "sRGB"
    except Exception:
        pass
    return img
