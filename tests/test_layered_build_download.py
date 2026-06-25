# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import importlib.util
import os
from pathlib import Path
from urllib.error import URLError
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD_PY = ROOT / "src/scripts/mixar/modules/paint/layered_build/download.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


download = _load("lb_download", DOWNLOAD_PY)


def test_filename_for_url_keeps_extension():
    assert download._filename_for_url("https://s3/abc/basecolor_12ab.png").endswith(".png")


def test_download_to_tempfile_writes_bytes(tmp_path):
    fake = MagicMock()
    fake.read.return_value = b"PNGDATA"
    with patch("urllib.request.urlopen") as uo:
        uo.return_value.__enter__.return_value = fake
        path = download.download_to_tempfile("https://s3/x/basecolor.png", dest_dir=str(tmp_path))
    assert os.path.exists(path)
    with open(path, "rb") as f:
        assert f.read() == b"PNGDATA"


def test_download_to_tempfile_retries_transient_url_errors(tmp_path):
    fake = MagicMock()
    fake.read.return_value = b"PNGDATA"
    with patch("urllib.request.urlopen") as uo, patch("time.sleep") as sleep:
        uo.side_effect = [
            URLError(ConnectionResetError(54, "Connection reset by peer")),
            MagicMock(__enter__=MagicMock(return_value=fake), __exit__=MagicMock(return_value=False)),
        ]
        path = download.download_to_tempfile(
            "https://s3/x/basecolor.png",
            dest_dir=str(tmp_path),
            attempts=2,
            backoff_seconds=0.01,
        )

    assert os.path.exists(path)
    with open(path, "rb") as f:
        assert f.read() == b"PNGDATA"
    assert uo.call_count == 2
    sleep.assert_called_once()


def test_download_to_tempfile_does_not_leave_partial_file_after_failure(tmp_path):
    with patch("urllib.request.urlopen", side_effect=URLError("reset")):
        with pytest.raises(URLError):
            download.download_to_tempfile(
                "https://s3/x/basecolor.png",
                dest_dir=str(tmp_path),
                attempts=1,
            )

    assert not any(path.name.endswith(".part") for path in tmp_path.iterdir())


@pytest.mark.parametrize(
    "bad_url",
    [
        "file:///home/user/.env",
        "ftp://host/secret.png",
        "data:text/plain;base64,SGVsbG8=",
        "/etc/passwd",
        "FILE:///etc/passwd",
    ],
)
def test_download_to_tempfile_rejects_non_http(tmp_path, bad_url):
    """A manifest must never coax a non-http(s) URL into a local file read."""
    with patch("urllib.request.urlopen") as uo:
        with pytest.raises(ValueError):
            download.download_to_tempfile(bad_url, dest_dir=str(tmp_path))
    uo.assert_not_called()
