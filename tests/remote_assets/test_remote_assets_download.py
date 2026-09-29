# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The shared verified download: cross-process resume and kept partials.

The updater's own cases (checksum gate, in-call Range resume, cancel) live
in ``tests/test_update_staging_download.py`` and now exercise this module
through the updater's wrapper.
"""

import hashlib
import io
import sys
from pathlib import Path
from unittest.mock import MagicMock

if "bpy" not in sys.modules:
    sys.modules["bpy"] = MagicMock(name="bpy")

import pytest  # noqa: E402

from mixar.modules.common.remote_assets.core import download  # noqa: E402


class _Resp(io.BytesIO):
    def __init__(self, data, status, total):
        super().__init__(data)
        self._status = status
        self.headers = {"Content-Length": str(total)}

    def getcode(self):
        return self._status


def _fast():
    return download.Policy(retry_backoff_s=0.0, max_attempts=2)


def test_resume_existing_hashes_the_partial_and_asks_for_the_rest(monkeypatch, tmp_path):
    payload = b"0123456789" * 20
    final = str(tmp_path / "part-0.mp4")
    Path(final + ".part").write_bytes(payload[:70])
    ranges = []

    def _open(request, timeout=None):
        header = request.get_header("Range")
        ranges.append(header)
        start = int(header.split("=")[1].split("-")[0])
        return _Resp(payload[start:], 206, len(payload) - start)

    monkeypatch.setattr(download.urllib.request, "urlopen", _open)
    out = download.download_file("https://cdn/x", final, hashlib.sha256(payload).hexdigest(),
                                 policy=_fast(), resume_existing=True)
    assert out == final
    assert Path(final).read_bytes() == payload
    assert ranges == ["bytes=70-"]


def test_keep_partial_leaves_bytes_for_the_next_launch(monkeypatch, tmp_path):
    payload = b"abcdefghij" * 10
    final = str(tmp_path / "part-1.mp4")

    def _open(request, timeout=None):
        # Always short: claims the full length, delivers less.
        return _Resp(payload[:30], 200, len(payload))

    monkeypatch.setattr(download.urllib.request, "urlopen", _open)
    with pytest.raises(download.DownloadError) as info:
        download.download_file("https://cdn/x", final, hashlib.sha256(payload).hexdigest(),
                               policy=_fast(), keep_partial=True)
    assert info.value.retryable
    assert Path(final + ".part").exists()
    assert not Path(final).exists()


def test_checksum_mismatch_never_keeps_the_partial(monkeypatch, tmp_path):
    payload = b"x" * 50
    final = str(tmp_path / "part-2.mp4")
    monkeypatch.setattr(download.urllib.request, "urlopen",
                        lambda request, timeout=None: _Resp(payload, 200, len(payload)))
    with pytest.raises(download.DownloadError) as info:
        download.download_file("https://cdn/x", final, "00" * 32, policy=_fast(),
                               keep_partial=True)
    assert not info.value.retryable
    assert not Path(final + ".part").exists()


def test_missing_sha_is_refused_before_any_request(monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr(download.urllib.request, "urlopen",
                        lambda *a, **k: called.append(1))
    with pytest.raises(download.DownloadError):
        download.download_file("https://cdn/x", str(tmp_path / "f"), "", policy=_fast())
    assert not called


def test_policy_error_classes_are_raised(monkeypatch, tmp_path):
    class MyErr(download.DownloadError):
        pass

    class MyCancel(MyErr):
        def __init__(self):
            super().__init__("c", user_message="Cancelled")

    policy = download.Policy(retry_backoff_s=0.0, error_cls=MyErr, cancelled_cls=MyCancel)
    monkeypatch.setattr(download.urllib.request, "urlopen",
                        lambda request, timeout=None: _Resp(b"data", 200, 4))
    with pytest.raises(MyCancel):
        download.download_file("https://cdn/x", str(tmp_path / "f"), "ab" * 32,
                               policy=policy, should_cancel=lambda: True)
