# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The manifest request names the app: cdn.mixar.app answers urllib's
default ``Python-urllib/3.x`` user agent with a 403 (Cloudflare 1010),
which left every dubbed language on English with subtitles."""

import io
import json
import sys
from unittest.mock import MagicMock

if "bpy" not in sys.modules:
    sys.modules["bpy"] = MagicMock(name="bpy")

from mixar.modules.onboarding.core.tour import pack_fetch, packs  # noqa: E402


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_manifest_request_sends_a_mixar_user_agent(monkeypatch, tmp_path):
    seen = []

    def _open(request, timeout=None):
        seen.append(request.get_header("User-agent"))
        return _Resp(json.dumps({"pack_version": 2, "languages": {}}).encode())

    monkeypatch.setattr(pack_fetch.urllib.request, "urlopen", _open)
    manifest = pack_fetch.fetch_manifest(str(tmp_path))
    assert manifest == {"pack_version": 2, "languages": {}}
    assert seen and seen[0].startswith("Mixar")
    assert packs.read_manifest(str(tmp_path)) == manifest
