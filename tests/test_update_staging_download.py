# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Staging-directory choice and installer download/verification.

The staging directory is the fix for the Windows failure this feature
exists to remove — a per-user temp path that an elevating admin account
cannot read — so its ordering and its ``shared`` flag are pinned here.
"""

import hashlib
import io
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

for _name in ("blf", "gpu", "gpu.state", "gpu.shader", "gpu_extras", "gpu_extras.batch"):
    sys.modules.setdefault(_name, MagicMock(name=_name))

import pytest

from mixar.modules.common.updates.core import download, staging


def setup_function(_fn):
    # resolve_staging_dir() caches per process; each case resolves fresh.
    staging._resolved = None


# ---------------------------------------------------------------------------
# Staging directory
# ---------------------------------------------------------------------------


def test_windows_prefers_programdata_over_user_temp(monkeypatch, tmp_path):
    """ProgramData first: %LOCALAPPDATA% is unreadable to another admin."""
    program_data = tmp_path / "ProgramData"
    local_appdata = tmp_path / "Local"
    program_data.mkdir()
    local_appdata.mkdir()

    monkeypatch.setattr(staging, "_is_windows", lambda: True)
    monkeypatch.setenv("ProgramData", str(program_data))
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))
    monkeypatch.setattr(staging, "_grant_machine_read", lambda path: None)

    resolved = staging.resolve_staging_dir()

    assert resolved.path.startswith(str(program_data))
    assert resolved.shared is True
    assert os.path.isdir(resolved.path)


def test_windows_falls_back_to_local_appdata_and_flags_it(monkeypatch, tmp_path):
    """An unusable ProgramData must not block the update, only downgrade it."""
    local_appdata = tmp_path / "Local"
    local_appdata.mkdir()

    monkeypatch.setattr(staging, "_is_windows", lambda: True)
    monkeypatch.setenv("ProgramData", str(tmp_path / "missing"))
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))
    monkeypatch.setattr(staging, "_grant_machine_read", lambda path: None)

    real_is_usable = staging._is_usable

    def _only_local(path):
        if "missing" in path:
            return False
        return real_is_usable(path)

    monkeypatch.setattr(staging, "_is_usable", _only_local)

    resolved = staging.resolve_staging_dir()

    assert resolved.path.startswith(str(local_appdata))
    assert resolved.shared is False


def test_staging_paths_are_versioned_and_purge_keeps_named_files(tmp_path):
    resolved = staging.StagingDir(str(tmp_path), True)
    path = staging.installer_path(resolved, "3.4.0", ".msi")
    assert os.path.basename(path) == "Mixar-3.4.0.msi"

    Path(path).write_text("new")
    (tmp_path / "Mixar-3.3.9.msi").write_text("old")
    (tmp_path / "mixar-update-3.3.9.cmd").write_text("stale helper")

    staging.purge_stale(resolved, keep_filenames=("Mixar-3.4.0.msi",))

    assert os.path.isfile(path)
    assert not (tmp_path / "Mixar-3.3.9.msi").exists()
    assert not (tmp_path / "mixar-update-3.3.9.cmd").exists()


# ---------------------------------------------------------------------------
# Download + verification
# ---------------------------------------------------------------------------


class _FakeResponse(io.BytesIO):
    def __init__(self, payload, status=200, content_length=None, headers=None):
        super().__init__(payload)
        self._status = status
        self.headers = headers or {}
        if content_length is None:
            content_length = len(payload)
        if content_length >= 0:
            self.headers.setdefault("Content-Length", str(content_length))

    def getcode(self):
        return self._status


def _serve(payload, **kwargs):
    def _open(request, timeout=None):
        return _FakeResponse(payload, **kwargs)
    return _open


def test_download_renames_only_after_checksum_matches(monkeypatch, tmp_path):
    payload = b"installer-bytes" * 100
    digest = hashlib.sha256(payload).hexdigest()
    final = str(tmp_path / "Mixar-3.4.0.msi")

    monkeypatch.setattr(download.urllib.request, "urlopen", _serve(payload))

    assert download.download_installer("https://x/i.msi", final, digest) == final
    assert Path(final).read_bytes() == payload
    assert not Path(final + ".part").exists()


def test_download_rejects_a_mismatched_checksum(monkeypatch, tmp_path):
    payload = b"tampered"
    final = str(tmp_path / "Mixar-3.4.0.msi")

    monkeypatch.setattr(download.urllib.request, "urlopen", _serve(payload))

    with pytest.raises(download.UpdateDownloadError) as excinfo:
        download.download_installer("https://x/i.msi", final, "0" * 64)

    assert not Path(final).exists()
    assert not Path(final + ".part").exists()
    assert excinfo.value.retryable is False


def test_http_failure_detail_reaches_the_user_message(monkeypatch, tmp_path):
    """"Download failed (HTTP 404)" on the toast is what makes a broken
    release row diagnosable without a console."""
    import urllib.error

    def _raise(request, timeout=None):
        raise urllib.error.HTTPError("https://x/i.msi", 404, "Not Found", {}, None)

    monkeypatch.setattr(download.urllib.request, "urlopen", _raise)
    monkeypatch.setattr(download, "DOWNLOAD_RETRY_BACKOFF_S", 0.0)

    with pytest.raises(download.UpdateDownloadError) as excinfo:
        download.download_installer(
            "https://x/i.msi", str(tmp_path / "i.msi"), "0" * 64,
        )
    assert excinfo.value.user_message == "Download failed (HTTP 404)"
    assert excinfo.value.retryable is False


def test_download_requires_a_checksum_at_all(tmp_path):
    with pytest.raises(download.UpdateDownloadError):
        download.download_installer("https://x/i.msi", str(tmp_path / "i.msi"), "")


def test_truncated_body_is_not_staged(monkeypatch, tmp_path):
    payload = b"half"
    final = str(tmp_path / "Mixar-3.4.0.msi")
    monkeypatch.setattr(
        download.urllib.request, "urlopen", _serve(payload, content_length=999),
    )
    monkeypatch.setattr(download, "DOWNLOAD_RETRY_BACKOFF_S", 0.0)

    with pytest.raises(download.UpdateDownloadError):
        download.download_installer(
            "https://x/i.msi", final, hashlib.sha256(payload).hexdigest(),
        )
    assert not Path(final).exists()


def test_resume_continues_from_verified_bytes(monkeypatch, tmp_path):
    """A dropped 400 MB transfer must not restart from zero."""
    payload = b"abcdefghij" * 10
    digest = hashlib.sha256(payload).hexdigest()
    final = str(tmp_path / "Mixar-3.4.0.msi")
    ranges = []

    class _Flaky(io.BytesIO):
        def __init__(self, data, status, total):
            super().__init__(data)
            self._status = status
            self.headers = {"Content-Length": str(total)}

        def getcode(self):
            return self._status

    def _open(request, timeout=None):
        header = request.get_header("Range")
        ranges.append(header)
        if header is None:
            # First attempt: claim the full length, deliver half.
            return _Flaky(payload[:40], 200, len(payload))
        start = int(header.split("=")[1].split("-")[0])
        return _Flaky(payload[start:], 206, len(payload) - start)

    monkeypatch.setattr(download.urllib.request, "urlopen", _open)
    monkeypatch.setattr(download, "DOWNLOAD_RETRY_BACKOFF_S", 0.0)

    assert download.download_installer("https://x/i.msi", final, digest) == final
    assert Path(final).read_bytes() == payload
    assert ranges == [None, "bytes=40-"]


def test_cancel_removes_the_partial_file(monkeypatch, tmp_path):
    payload = b"x" * (4 * 1024 * 1024)
    final = str(tmp_path / "Mixar-3.4.0.msi")
    monkeypatch.setattr(download.urllib.request, "urlopen", _serve(payload))

    with pytest.raises(download.UpdateDownloadCancelled):
        download.download_installer(
            "https://x/i.msi", final, hashlib.sha256(payload).hexdigest(),
            should_cancel=lambda: True,
        )
    assert not Path(final).exists()
    assert not Path(final + ".part").exists()
