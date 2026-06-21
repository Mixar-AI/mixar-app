# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import importlib.util
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

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
