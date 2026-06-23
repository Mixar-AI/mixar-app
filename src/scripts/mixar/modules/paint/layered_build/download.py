# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Download manifest assets (PBR maps, masks) into temp files and bpy.data.images."""

import hashlib
import os
import tempfile
import urllib.parse
import urllib.request

import bpy

# Manifests are authored by the AI backend and can be influenced by user
# prompts. Restrict downloads to remote http(s) assets so URLs such as
# file:///home/user/.env cannot read local files into bpy.data.images.
_ALLOWED_SCHEMES = ("http", "https")


def _filename_for_url(url: str) -> str:
    base = url.split("?", 1)[0].rsplit("/", 1)[-1] or "asset"
    if "." not in base:
        base += ".png"
    digest = hashlib.sha1(url.encode()).hexdigest()[:8]
    stem, ext = os.path.splitext(base)
    return f"{stem}_{digest}{ext}"


def download_to_tempfile(url: str, dest_dir: str = None, timeout: float = 30.0) -> str:
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise ValueError(
            f"Refusing to download asset from non-http(s) URL (scheme={scheme!r}): {url!r}"
        )
    dest_dir = dest_dir or os.path.join(tempfile.gettempdir(), "mixar_layered_build")
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, _filename_for_url(url))
    if not os.path.exists(path):
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = resp.read()
        with open(path, "wb") as f:
            f.write(data)
    return path


def load_image(url: str, non_color: bool) -> "bpy.types.Image":
    """Download url and load as a bpy image, setting colorspace."""
    path = download_to_tempfile(url)
    img = bpy.data.images.load(path, check_existing=True)
    try:
        img.colorspace_settings.name = "Non-Color" if non_color else "sRGB"
    except Exception:
        pass
    return img
