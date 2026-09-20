# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Verified resumable downloader: policy pinned with a fake opener."""

import hashlib

import pytest

from mixar.modules.local_models.core import download
from mixar.modules.local_models.core.download import (
    DownloadCancelled,
    DownloadError,
    download_file,
)

PAYLOAD = bytes(range(256)) * 400  # 102400 bytes, deterministic
SHA = hashlib.sha256(PAYLOAD).hexdigest()
URL = "https://example.com/model.gguf"


class FakeResponse:
    def __init__(self, data, status=200, content_length=None):
        self._data = data
        self._pos = 0
        self.status = status
        self.headers = {}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)

    def read(self, n):
        chunk = self._data[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk

    def close(self):
        pass


def install_opener(monkeypatch, handlers):
    """Each handler: fn(request) -> FakeResponse (or raises). Consumed in
    order; records every request for assertions."""
    seen = []
    remaining = list(handlers)

    def fake_urlopen(request, timeout=None):
        seen.append(request)
        assert timeout and timeout > 0
        if not remaining:
            raise AssertionError("unexpected extra request")
        return remaining.pop(0)(request)

    monkeypatch.setattr(download, "_urlopen", fake_urlopen)
    return seen


def fast_backoff(monkeypatch):
    monkeypatch.setattr(download, "DOWNLOAD_RETRY_BACKOFF_S", 0.01)


def test_happy_path_verifies_and_renames(monkeypatch, tmp_path):
    dest = str(tmp_path / "model.gguf")
    install_opener(monkeypatch, [
        lambda req: FakeResponse(PAYLOAD, content_length=len(PAYLOAD)),
    ])
    result = download_file(
        URL, dest, expected_sha256=SHA, expected_size=len(PAYLOAD),
        deadline_s=30,
    )
    assert result == dest
    with open(dest, "rb") as handle:
        assert handle.read() == PAYLOAD
    assert not (tmp_path / "model.gguf.part").exists()


def test_https_only(monkeypatch, tmp_path):
    seen = install_opener(monkeypatch, [])
    with pytest.raises(DownloadError):
        download_file("http://example.com/f", str(tmp_path / "f"), deadline_s=5)
    assert seen == []


def test_sha_mismatch_is_terminal_and_cleans_part(monkeypatch, tmp_path):
    dest = str(tmp_path / "model.gguf")
    install_opener(monkeypatch, [
        lambda req: FakeResponse(PAYLOAD, content_length=len(PAYLOAD)),
    ])
    with pytest.raises(DownloadError) as excinfo:
        download_file(
            URL, dest, expected_sha256="0" * 64,
            expected_size=len(PAYLOAD), deadline_s=30,
        )
    assert not excinfo.value.retryable
    assert not (tmp_path / "model.gguf.part").exists()
    assert not (tmp_path / "model.gguf").exists()


def test_short_read_retries_with_range_resume(monkeypatch, tmp_path):
    fast_backoff(monkeypatch)
    dest = str(tmp_path / "model.gguf")

    def first(req):
        assert req.headers.get("Range") is None
        # Claims the full length but streams only half -> retryable.
        return FakeResponse(PAYLOAD[:51200], content_length=len(PAYLOAD))

    def second(req):
        assert req.headers.get("Range") == "bytes=51200-"
        return FakeResponse(PAYLOAD[51200:], status=206,
                            content_length=len(PAYLOAD) - 51200)

    seen = install_opener(monkeypatch, [first, second])
    result = download_file(
        URL, dest, expected_sha256=SHA, expected_size=len(PAYLOAD),
        deadline_s=30,
    )
    assert result == dest
    assert len(seen) == 2
    with open(dest, "rb") as handle:
        assert handle.read() == PAYLOAD


def test_cancel_raises_and_keeps_part_for_resume(monkeypatch, tmp_path):
    dest = str(tmp_path / "model.gguf")
    install_opener(monkeypatch, [
        lambda req: FakeResponse(PAYLOAD, content_length=len(PAYLOAD)),
    ])
    with pytest.raises(DownloadCancelled):
        download_file(
            URL, dest, expected_sha256=SHA, expected_size=len(PAYLOAD),
            should_cancel=lambda: True, deadline_s=30,
        )
    assert not (tmp_path / "model.gguf").exists()


def test_resume_rehashes_existing_prefix(monkeypatch, tmp_path):
    dest = str(tmp_path / "model.gguf")
    part = tmp_path / "model.gguf.part"
    part.write_bytes(PAYLOAD[:40000])

    def resumed(req):
        assert req.headers.get("Range") == "bytes=40000-"
        return FakeResponse(PAYLOAD[40000:], status=206,
                            content_length=len(PAYLOAD) - 40000)

    install_opener(monkeypatch, [resumed])
    result = download_file(
        URL, dest, expected_sha256=SHA, expected_size=len(PAYLOAD),
        deadline_s=30,
    )
    # The final digest covered the pre-existing prefix too, or the
    # expected_sha256 check would have failed.
    assert result == dest
    with open(dest, "rb") as handle:
        assert handle.read() == PAYLOAD


def test_resume_restarts_when_server_ignores_range(monkeypatch, tmp_path):
    dest = str(tmp_path / "model.gguf")
    part = tmp_path / "model.gguf.part"
    part.write_bytes(b"stale-bytes-from-last-time")

    def ignores_range(req):
        assert req.headers.get("Range") is not None
        return FakeResponse(PAYLOAD, status=200, content_length=len(PAYLOAD))

    install_opener(monkeypatch, [ignores_range])
    result = download_file(
        URL, dest, expected_sha256=SHA, expected_size=len(PAYLOAD),
        deadline_s=30,
    )
    assert result == dest
    with open(dest, "rb") as handle:
        assert handle.read() == PAYLOAD


def test_progress_reports_transferred_and_total(monkeypatch, tmp_path):
    dest = str(tmp_path / "model.gguf")
    install_opener(monkeypatch, [
        lambda req: FakeResponse(PAYLOAD, content_length=len(PAYLOAD)),
    ])
    calls = []
    download_file(
        URL, dest, expected_sha256=SHA, expected_size=len(PAYLOAD),
        on_progress=lambda t, total, attempt: calls.append((t, total, attempt)),
        deadline_s=30,
    )
    assert calls[0] == (0, len(PAYLOAD), 1)
    assert calls[-1] == (len(PAYLOAD), len(PAYLOAD), 1)


def test_default_deadline_scales_with_size():
    assert download.default_deadline_s(None) == 900
    assert download.default_deadline_s(10 * 1024 ** 2) == 900
    seventeen_gb = 17 * 1024 ** 3
    assert download.default_deadline_s(seventeen_gb) == seventeen_gb // (200 * 1024)


class StallingResponse(FakeResponse):
    """Streams *stall_after* bytes, then raises TimeoutError mid-body."""

    def __init__(self, data, stall_after, **kwargs):
        super().__init__(data, **kwargs)
        self._stall_after = stall_after

    def read(self, n):
        if self._pos >= self._stall_after:
            raise TimeoutError("stalled")
        return super().read(min(n, self._stall_after - self._pos))


def test_midbody_stall_resumes_at_actual_offset(monkeypatch, tmp_path):
    """Regression: a mid-body stall must advance the resume offset so the
    in-process retry Ranges past the bytes already written+hashed —
    previously the retry re-downloaded from 0 with a stale hasher and
    terminally failed verification."""
    fast_backoff(monkeypatch)
    dest = str(tmp_path / "model.gguf")

    def first(req):
        assert req.headers.get("Range") is None
        return StallingResponse(PAYLOAD, 65536, content_length=len(PAYLOAD))

    def second(req):
        assert req.headers.get("Range") == "bytes=65536-"
        return FakeResponse(PAYLOAD[65536:], status=206,
                            content_length=len(PAYLOAD) - 65536)

    seen = install_opener(monkeypatch, [first, second])
    result = download_file(
        URL, dest, expected_sha256=SHA, expected_size=len(PAYLOAD),
        deadline_s=30,
    )
    assert result == dest
    assert len(seen) == 2
    with open(dest, "rb") as handle:
        assert handle.read() == PAYLOAD


def test_midbody_drop_on_resumed_part_ranges_past_new_bytes(monkeypatch, tmp_path):
    """A resumed transfer that drops mid-append must Range past prefix+new
    bytes on retry, not re-append the same region."""
    fast_backoff(monkeypatch)
    dest = str(tmp_path / "model.gguf")
    part = tmp_path / "model.gguf.part"
    part.write_bytes(PAYLOAD[:40000])

    def resumed(req):
        assert req.headers.get("Range") == "bytes=40000-"
        return StallingResponse(PAYLOAD[40000:], 20000, status=206,
                                content_length=len(PAYLOAD) - 40000)

    def final(req):
        assert req.headers.get("Range") == "bytes=60000-"
        return FakeResponse(PAYLOAD[60000:], status=206,
                            content_length=len(PAYLOAD) - 60000)

    install_opener(monkeypatch, [resumed, final])
    result = download_file(
        URL, dest, expected_sha256=SHA, expected_size=len(PAYLOAD),
        deadline_s=30,
    )
    assert result == dest
    with open(dest, "rb") as handle:
        assert handle.read() == PAYLOAD
