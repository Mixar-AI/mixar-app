# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Manifest asset prefetch: URL collection, concurrent download, fail-fast cache.

The agent apply script runs synchronously on Blender's main thread; serial
in-build downloads froze the UI (macOS beach ball) for the SUM of all fetches.
These tests pin the prefetch contract that removes that freeze:
- collect_asset_urls splits required (base PBR maps) from optional (masks);
- prefetch_urls downloads concurrently and reports failures per URL;
- a URL that exhausted retries fails fast on re-request (no second freeze).
"""

import threading
import time

import pytest

from src.scripts.mixar.modules.paint.layered_build import download as download_mod
from src.scripts.mixar.modules.paint.layered_build.download import prefetch_urls
from src.scripts.mixar.modules.paint.layered_build.manifest import collect_asset_urls


def _manifest():
    return {
        "material_name": "Weathered Oak",
        "layers": [
            {
                "index": 0,
                "type": "PBR",
                "maps": {
                    "basecolor": "https://x/base.png",
                    "roughness": "https://x/rough.png",
                    "normal": "https://x/normal.png",
                    "height": "",  # empty -> skipped
                },
            },
            {
                "index": 1,
                "type": "PROCEDURAL",
                "masks": [
                    {"type": "IMAGE", "image_url": "https://x/mask1.png"},
                    {"type": "BAKED", "bake_type": "AO"},  # no url -> skipped
                    {"type": "IMAGE", "image_url": "https://x/base.png"},  # dup of required
                ],
            },
        ],
    }


class TestCollectAssetUrls:
    def test_splits_required_and_optional(self):
        required, optional = collect_asset_urls(_manifest())
        assert required == [
            "https://x/base.png",
            "https://x/rough.png",
            "https://x/normal.png",
        ]
        # The duplicate of a required URL is dropped from optional.
        assert optional == ["https://x/mask1.png"]

    def test_empty_manifest(self):
        assert collect_asset_urls({}) == ([], [])


class TestPrefetchUrls:
    def test_downloads_run_concurrently(self, monkeypatch):
        """N slow downloads must overlap — the whole point of the prefetch.
        A barrier all workers must reach together deadlocks (-> timeout ->
        failure entries) if downloads were serial."""
        barrier = threading.Barrier(3, timeout=5.0)

        def fake_download(url, timeout=30.0, **kwargs):
            barrier.wait()
            return "/tmp/" + url.rsplit("/", 1)[-1]

        monkeypatch.setattr(download_mod, "download_to_tempfile", fake_download)
        errors = prefetch_urls([f"https://x/{i}.png" for i in range(3)])
        assert errors == {}

    def test_collects_failures_and_dedupes(self, monkeypatch):
        seen = []

        def fake_download(url, timeout=30.0, **kwargs):
            seen.append(url)
            if "bad" in url:
                raise ValueError("boom")
            return "/tmp/ok.png"

        monkeypatch.setattr(download_mod, "download_to_tempfile", fake_download)
        errors = prefetch_urls(
            ["https://x/ok.png", "https://x/bad.png", "https://x/ok.png", ""]
        )
        assert list(errors) == ["https://x/bad.png"]
        assert "ValueError" in errors["https://x/bad.png"]
        assert seen.count("https://x/ok.png") == 1  # deduped

    def test_empty_input(self):
        assert prefetch_urls([]) == {}


class TestFailFastNegativeCache:
    def test_recent_failure_raises_immediately(self, monkeypatch, tmp_path):
        """After a URL exhausts its retries, a re-request within the TTL must
        not touch the network again — load_image would otherwise re-pay the
        full attempts*timeout wait on the main thread."""
        monkeypatch.setattr(download_mod, "_recent_failures", {})
        calls = {"n": 0}

        def fake_read(url, timeout):
            calls["n"] += 1
            raise ValueError("dead url")

        monkeypatch.setattr(download_mod, "_read_url", fake_read)
        url = "https://x/gone.png"
        with pytest.raises(ValueError):
            download_mod.download_to_tempfile(url, dest_dir=str(tmp_path))
        assert calls["n"] == 1  # non-retryable -> single attempt

        with pytest.raises(ValueError):
            download_mod.download_to_tempfile(url, dest_dir=str(tmp_path))
        assert calls["n"] == 1  # fail-fast: no new network attempt

    def test_failure_expires_after_ttl(self, monkeypatch, tmp_path):
        monkeypatch.setattr(download_mod, "_recent_failures", {})
        monkeypatch.setattr(download_mod, "_FAILURE_TTL_SECONDS", 0.01)

        def fake_read(url, timeout):
            raise ValueError("dead url")

        monkeypatch.setattr(download_mod, "_read_url", fake_read)
        url = "https://x/gone.png"
        with pytest.raises(ValueError):
            download_mod.download_to_tempfile(url, dest_dir=str(tmp_path))
        time.sleep(0.02)

        def fake_read_ok(url, timeout):
            return b"png-bytes"

        monkeypatch.setattr(download_mod, "_read_url", fake_read_ok)
        path = download_mod.download_to_tempfile(url, dest_dir=str(tmp_path))
        assert path.endswith(".png")

    def test_success_is_not_poisoned_by_other_urls(self, monkeypatch, tmp_path):
        monkeypatch.setattr(download_mod, "_recent_failures", {})

        def fake_read(url, timeout):
            return b"png-bytes"

        monkeypatch.setattr(download_mod, "_read_url", fake_read)
        path = download_mod.download_to_tempfile("https://x/fine.png", dest_dir=str(tmp_path))
        assert path.endswith(".png")
