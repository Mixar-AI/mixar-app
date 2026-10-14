# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The tour manifest fetch: it names the app (cdn.mixar.app answers urllib's
default ``Python-urllib/3.x`` with a 403, Cloudflare error 1010, which left
every dubbed language on English with subtitles), reads its own pack
version's manifest, and never caches another version's."""

import io
import json
import sys
from unittest.mock import MagicMock

if "bpy" not in sys.modules:
    sys.modules["bpy"] = MagicMock(name="bpy")

from mixar.modules.onboarding.core.tour import config, pack_fetch, packs  # noqa: E402


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _serve(monkeypatch, manifest, seen):
    def _open(request, timeout=None):
        seen.append((request.full_url, request.get_header("User-agent")))
        return _Resp(json.dumps(manifest).encode())
    monkeypatch.setattr(pack_fetch.urllib.request, "urlopen", _open)


def test_manifest_url_is_this_clients_pack_version():
    """Old clients keep reading tour-packs/manifest.json (version 1), so a
    new version's packs never take their dubs away."""
    assert config.PACKS_MANIFEST_URL == (
        f"https://cdn.mixar.app/tour-packs/{config.TOUR_PACK_VERSION}/manifest.json")


def test_manifest_request_names_the_app(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(pack_fetch.dl, "_client_version", lambda: "4.3.0")
    manifest = {"pack_version": config.TOUR_PACK_VERSION, "languages": {}}
    _serve(monkeypatch, manifest, seen)
    assert pack_fetch.fetch_manifest(str(tmp_path)) == manifest
    assert seen == [(config.PACKS_MANIFEST_URL, "Mixar/4.3.0")]
    assert packs.read_manifest(str(tmp_path)) == manifest


def test_another_versions_manifest_is_never_cached(monkeypatch, tmp_path):
    good = {"pack_version": config.TOUR_PACK_VERSION, "languages": {"fr": {}}}
    _serve(monkeypatch, good, [])
    pack_fetch.fetch_manifest(str(tmp_path))
    _serve(monkeypatch, {"pack_version": config.TOUR_PACK_VERSION + 1, "languages": {}}, [])
    assert pack_fetch.fetch_manifest(str(tmp_path)) == good
    assert packs.read_manifest(str(tmp_path)) == good
