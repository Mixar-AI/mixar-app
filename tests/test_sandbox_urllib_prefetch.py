# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""RestrictedUrllib.prefetch — concurrent, allowlist-gated bulk downloads.

Agent scripts run on Blender's main thread; sequential multi-MB GETs for a
texture/asset set froze the app past the backend tool timeout. prefetch keeps
the same security boundary as urlopen (scheme + host gate per URL, paths-only
results) while the threads live outside the sandbox namespace.
"""

import importlib.util
from pathlib import Path
import tempfile

_SANDBOX_MODULES = (
    Path(__file__).parents[1]
    / "src/scripts/mixar/modules/space_mixie_chat/core/sandbox_modules.py"
)


def _load_sandbox_modules():
    spec = importlib.util.spec_from_file_location("sandbox_modules_under_test", _SANDBOX_MODULES)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeResponse:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data


def _urllib_with_fake_transport(payloads):
    mod = _load_sandbox_modules()
    restricted = mod.RestrictedUrllib()

    def fake_urlopen(url, timeout=120):
        if url in payloads:
            return _FakeResponse(payloads[url])
        raise OSError("connection refused")

    restricted._urlopen = fake_urlopen
    return restricted


def test_prefetch_downloads_allowed_urls_to_temp_paths():
    urls = [
        "https://bucket.s3.amazonaws.com/a.png",
        "https://bucket.s3.amazonaws.com/b.png",
    ]
    restricted = _urllib_with_fake_transport({urls[0]: b"aaa", urls[1]: b"bbb"})

    out = restricted.prefetch(urls)

    assert set(out) == set(urls)
    tmp = tempfile.gettempdir()
    for url, payload in ((urls[0], b"aaa"), (urls[1], b"bbb")):
        path = out[url]
        assert path is not None and path.startswith(tmp)
        with open(path, "rb") as fh:
            assert fh.read() == payload


def test_prefetch_refuses_disallowed_hosts_and_schemes_per_url():
    good = "https://bucket.s3.amazonaws.com/ok.png"
    restricted = _urllib_with_fake_transport({good: b"ok"})

    out = restricted.prefetch(
        [
            good,
            "https://evil.example.com/steal.png",
            "file://amazonaws.com/etc/passwd",
        ]
    )

    assert out[good] is not None
    assert out["https://evil.example.com/steal.png"] is None
    assert out["file://amazonaws.com/etc/passwd"] is None


def test_prefetch_maps_failed_downloads_to_none_without_raising():
    good = "https://bucket.s3.amazonaws.com/ok.png"
    missing = "https://bucket.s3.amazonaws.com/missing.png"
    restricted = _urllib_with_fake_transport({good: b"ok"})

    out = restricted.prefetch([good, missing])

    assert out[good] is not None
    assert out[missing] is None


def test_prefetch_caps_batch_and_dedupes():
    url = "https://bucket.s3.amazonaws.com/dup.png"
    restricted = _urllib_with_fake_transport({url: b"x"})
    calls = []
    original = restricted._urlopen

    def counting(u, timeout=120):
        calls.append(u)
        return original(u, timeout=timeout)

    restricted._urlopen = counting

    out = restricted.prefetch([url] * 50)

    assert calls == [url]
    assert out[url] is not None


def test_urlopen_gate_unchanged():
    restricted = _urllib_with_fake_transport({})
    try:
        restricted.urlopen("https://evil.example.com/x")
        raise AssertionError("expected PermissionError")
    except PermissionError:
        pass
