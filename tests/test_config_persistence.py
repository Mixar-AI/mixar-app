# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Config persistence contract (``mixar/config/config.py``).

Pins the fix for the installed-Windows-build hang on the splash screen's
"Start with Zen Mode" / "Engine Mode" buttons: ``set_ui_mode`` wrote into
``<install>/5.0/config/mixar.json`` under ``C:\\Program Files``, and CPython's
``tempfile.mkstemp`` retried the unwritable directory ``TMP_MAX`` (2**31)
times on the main thread, because on Windows ``os.access(dir, W_OK)`` ignores
ACLs and mkstemp reads a ``PermissionError`` there as a name collision.

Contract:
* user-written keys persist to a per-user overlay, never the bundled file;
* the overlay only ever holds keys written through ``add_config``;
* reads merge the overlay over the bundled defaults (overlay wins);
* a write failure returns False immediately -- it never spins.
"""

import json
import os
import pathlib

import pytest

from mixar.config import config as cfg

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG_SRC = REPO_ROOT / "src" / "scripts" / "mixar" / "config" / "config.py"


@pytest.fixture
def paths(tmp_path, monkeypatch):
    """Isolated bundled + user config roots, mirrored onto the bpy stubs."""
    install_root = tmp_path / "install"
    user_root = tmp_path / "user" / "mixar"
    (install_root / "config").mkdir(parents=True)
    user_root.mkdir(parents=True)

    # Patch the bpy the module actually holds: other suites swap
    # sys.modules['bpy'] for their own stub mid-session, so the `bpy`
    # imported here can be a different object from cfg.bpy.
    monkeypatch.setattr(cfg.bpy.utils, "resource_path", lambda *_a, **_k: str(install_root))
    monkeypatch.setattr(cfg.bpy.utils, "user_resource", lambda *_a, **_k: str(user_root))
    monkeypatch.setattr(cfg, "_config", None)
    monkeypatch.setattr(cfg, "_user_overrides", {})

    bundled = install_root / "config" / "mixar.json"
    overlay = user_root / "mixar.json"
    return bundled, overlay


def _write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


BUNDLED = {"backend_url": "https://api.example.test", "environment": "Prod"}


class TestWritesGoToTheUserOverlay:
    def test_add_config_never_touches_the_bundled_file(self, paths):
        bundled, overlay = paths
        _write(bundled, BUNDLED)
        before = bundled.read_bytes()

        assert cfg.set_ui_mode(cfg.UI_MODE_PRO) is True

        assert bundled.read_bytes() == before
        assert _read(overlay) == {"ui_mode": cfg.UI_MODE_PRO}

    def test_overlay_holds_only_user_written_keys(self, paths):
        """A bundled key copied into the overlay would shadow the next build's
        value for it (backend_url, update channel) forever."""
        bundled, overlay = paths
        _write(bundled, BUNDLED)

        assert cfg.get_server_url() == BUNDLED["backend_url"]  # loads merged view
        cfg.add_config("share_usage_data", False)
        cfg.add_config("ui_mode", cfg.UI_MODE_AI)

        assert _read(overlay) == {"share_usage_data": False, "ui_mode": cfg.UI_MODE_AI}
        assert cfg.get_server_url() == BUNDLED["backend_url"]

    def test_keys_already_in_the_overlay_are_preserved(self, paths):
        bundled, overlay = paths
        _write(bundled, BUNDLED)
        _write(overlay, {"device_id": "abc123"})

        cfg.add_config("ui_mode", cfg.UI_MODE_PRO)

        assert _read(overlay) == {"device_id": "abc123", "ui_mode": cfg.UI_MODE_PRO}

    def test_no_temp_file_is_left_behind(self, paths):
        bundled, overlay = paths
        _write(bundled, BUNDLED)
        cfg.add_config("ui_mode", cfg.UI_MODE_PRO)
        assert sorted(p.name for p in overlay.parent.iterdir()) == ["mixar.json"]


class TestReadsMergeOverlayOverBundled:
    def test_overlay_wins_for_keys_present_in_both(self, paths):
        bundled, overlay = paths
        _write(bundled, {**BUNDLED, "ui_mode": cfg.UI_MODE_AI})
        _write(overlay, {"ui_mode": cfg.UI_MODE_PRO})

        assert cfg.get_ui_mode() == cfg.UI_MODE_PRO
        assert cfg.get_server_url() == BUNDLED["backend_url"]

    def test_legacy_values_written_into_the_bundled_file_still_read(self, paths):
        """Dev and macOS installs wrote ui_mode into the bundled file before
        the overlay existed; those users keep their choice."""
        bundled, _overlay = paths
        _write(bundled, {**BUNDLED, "ui_mode": cfg.UI_MODE_PRO})
        assert cfg.get_ui_mode() == cfg.UI_MODE_PRO

    def test_missing_overlay_is_not_an_error(self, paths):
        bundled, overlay = paths
        _write(bundled, BUNDLED)
        assert not overlay.exists()
        assert cfg.get_environment() == "Prod"
        assert cfg.get_ui_mode() == cfg.UI_MODE_AI


class TestWriteFailuresFailFast:
    def test_permission_error_returns_false_after_one_attempt(self, paths, monkeypatch):
        """The Windows hang: mkstemp retried a PermissionError 2**31 times."""
        bundled, overlay = paths
        _write(bundled, BUNDLED)
        calls = []
        real_open = os.open

        def denied(path, *args, **kwargs):
            calls.append(path)
            raise PermissionError(13, "Permission denied", str(path))

        monkeypatch.setattr(os, "open", denied)
        assert cfg.set_ui_mode(cfg.UI_MODE_PRO) is False
        monkeypatch.setattr(os, "open", real_open)

        assert len(calls) == 1
        assert not overlay.exists()
        # The session still runs with the requested mode.
        assert cfg.get_ui_mode() == cfg.UI_MODE_PRO

    def test_name_collisions_are_bounded(self, paths, monkeypatch):
        bundled, overlay = paths
        _write(bundled, BUNDLED)
        calls = []

        def exists(path, *args, **kwargs):
            calls.append(path)
            raise FileExistsError(17, "File exists", str(path))

        monkeypatch.setattr(os, "open", exists)
        with pytest.raises(FileExistsError):
            cfg._write_config_file(str(overlay), {"ui_mode": cfg.UI_MODE_PRO})
        assert len(calls) == cfg._TMP_CREATE_ATTEMPTS

    def test_unavailable_user_dir_returns_false(self, paths, monkeypatch):
        bundled, _overlay = paths
        _write(bundled, BUNDLED)
        monkeypatch.setattr(cfg.bpy.utils, "user_resource", lambda *_a, **_k: "")
        assert cfg.add_config("ui_mode", cfg.UI_MODE_PRO) is False


class TestSourceContract:
    def test_config_never_uses_mkstemp(self):
        """tempfile.mkstemp is the spin: keep the exclusive-create helper."""
        source = CONFIG_SRC.read_text(encoding="utf-8")
        assert "import tempfile" not in source
        assert "mkstemp(" not in source

    def test_user_overlay_lives_under_the_user_config_resource(self):
        source = CONFIG_SRC.read_text(encoding="utf-8")
        assert "user_resource('CONFIG'" in source
