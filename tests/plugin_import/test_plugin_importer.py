# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Import/enable contracts for ``plugin_import.core.importer``.

``bpy`` and ``addon_utils`` are MagicMocks under this suite, so these
pin the call contract — what the importer asks Blender to do, and in
what order — rather than real file copies. Both contracts here are
platform-neutral and matter equally on Windows, where the destination
is ``%APPDATA%/Mixar/5.0/scripts/addons``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mixar.modules.plugin_import.constants import (
    ENABLE_FAILED,
    ENABLE_OK,
    KIND_ADDON,
)
from mixar.modules.plugin_import.core import importer as imp
from mixar.modules.plugin_import.core.enumerate import PluginInfo


def _call_names(mock: MagicMock) -> list[str]:
    """Flattened attribute path of every call made on ``mock``."""
    return [name for name, _args, _kwargs in mock.mock_calls if name]


class TestRefreshPutsAddonsOnSysPath:
    """The High-severity first-run bug.

    ``mixar_addons_dir(create=True)`` may have *just created* the user
    addons dir, which means it was absent at startup and so never made it
    onto ``sys.path``. ``preferences.addon_refresh`` only rebuilds the
    bl_info cache — ``bpy.utils.refresh_script_paths()`` is the only call
    that fixes the path, and without it every legacy add-on copies in and
    then fails to enable with ModuleNotFoundError.
    """

    def test_refresh_script_paths_is_called(self, monkeypatch):
        bpy = MagicMock()
        monkeypatch.setattr(imp, "bpy", bpy)
        imp._refresh(any_extension=False)
        bpy.utils.refresh_script_paths.assert_called_once_with()

    def test_it_runs_before_the_metadata_rescan(self, monkeypatch):
        bpy = MagicMock()
        monkeypatch.setattr(imp, "bpy", bpy)
        imp._refresh(any_extension=False)
        names = _call_names(bpy)
        assert names.index("utils.refresh_script_paths") < names.index(
            "ops.preferences.addon_refresh"
        )

    def test_a_failing_refresh_never_aborts_the_batch(self, monkeypatch):
        bpy = MagicMock()
        bpy.utils.refresh_script_paths.side_effect = RuntimeError("boom")
        monkeypatch.setattr(imp, "bpy", bpy)
        imp._refresh(any_extension=False)          # must not raise
        bpy.ops.preferences.addon_refresh.assert_called_once()

    def test_the_path_is_refreshed_before_anything_is_enabled(
        self, monkeypatch, tmp_path
    ):
        """End-to-end ordering through import_all, not just _refresh."""
        order: list[str] = []
        monkeypatch.setattr(imp, "mixar_addons_dir", lambda: tmp_path / "addons")
        monkeypatch.setattr(
            imp, "target_extension_repo", lambda: ("user_default", tmp_path / "ext")
        )
        monkeypatch.setattr(
            imp, "_copy_in", lambda src, dst, is_dir: imp.STATUS_IMPORTED
        )
        monkeypatch.setattr(
            imp, "_refresh", lambda any_extension: order.append("refresh")
        )
        monkeypatch.setattr(
            imp, "_enable", lambda module_id: (order.append("enable"), (True, ""))[1]
        )
        monkeypatch.setattr(imp, "_save_userpref", lambda: None)

        plugin = PluginInfo(
            name="demo", kind=KIND_ADDON, path=tmp_path / "demo", is_dir=True
        )
        imp.import_all([plugin], {"demo": True})
        assert order == ["refresh", "enable"]


class TestEnableReportsTheRealReason:
    """``addon_utils.enable`` swallows the exception and returns None, so
    the reason has to be captured through ``handle_error`` or every
    failure reaches the user as the misleading "not found"."""

    def test_the_captured_exception_becomes_the_message(self, monkeypatch):
        def fake_enable(module_id, *, handle_error=None, **kwargs):
            handle_error(RuntimeError("needs Blender 9.9"))
            return None

        monkeypatch.setattr(imp.addon_utils, "enable", fake_enable)
        ok, err = imp._enable("some_addon")
        assert ok is False
        assert err == "RuntimeError: needs Blender 9.9"

    def test_a_handler_is_always_passed(self, monkeypatch):
        enable = MagicMock(return_value=MagicMock())
        monkeypatch.setattr(imp.addon_utils, "enable", enable)
        imp._enable("some_addon")
        assert callable(enable.call_args.kwargs["handle_error"])

    def test_silent_none_still_falls_back(self, monkeypatch):
        """No exception raised, module still missing — keep the old text."""
        monkeypatch.setattr(
            imp.addon_utils, "enable", lambda module_id, **kwargs: None
        )
        ok, err = imp._enable("some_addon")
        assert (ok, err) == (False, "add-on not found after import")

    def test_success_reports_no_error(self, monkeypatch):
        monkeypatch.setattr(
            imp.addon_utils, "enable", lambda module_id, **kwargs: MagicMock()
        )
        assert imp._enable("some_addon") == (True, "")

    def test_the_reason_reaches_the_checklist_row(self, monkeypatch, tmp_path):
        monkeypatch.setattr(imp, "mixar_addons_dir", lambda: tmp_path / "addons")
        monkeypatch.setattr(
            imp, "target_extension_repo", lambda: ("user_default", tmp_path / "ext")
        )
        monkeypatch.setattr(
            imp, "_copy_in", lambda src, dst, is_dir: imp.STATUS_IMPORTED
        )
        monkeypatch.setattr(imp, "_refresh", lambda any_extension: None)
        monkeypatch.setattr(imp, "_save_userpref", lambda: None)
        monkeypatch.setattr(
            imp, "_enable", lambda module_id: (False, "RuntimeError: nope")
        )

        plugin = PluginInfo(
            name="demo", kind=KIND_ADDON, path=tmp_path / "demo", is_dir=True
        )
        summary = imp.import_all([plugin], {"demo": True})
        assert summary.items[0].enable_status == ENABLE_FAILED
        assert summary.items[0].message == "RuntimeError: nope"


class TestUnresolvableDestinationFailsLoudly:
    """``user_resource`` returns "" when it cannot create the directory, and
    ``Path("")`` is ``Path(".")`` — unguarded, the whole import lands in the
    process CWD while reporting success. Most likely on Windows (redirected
    ``%APPDATA%``, OneDrive profiles, locked-down machines)."""

    def test_empty_resource_path_is_refused(self, monkeypatch):
        bpy = MagicMock()
        bpy.utils.user_resource.return_value = ""
        monkeypatch.setattr(imp, "bpy", bpy)
        with pytest.raises(imp.PluginImportUnavailable):
            imp.mixar_addons_dir()

    def test_nothing_is_copied_and_every_row_says_why(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            imp,
            "mixar_addons_dir",
            MagicMock(side_effect=imp.PluginImportUnavailable("no profile dir")),
        )
        copied = MagicMock()
        monkeypatch.setattr(imp, "_copy_in", copied)

        plugin = PluginInfo(
            name="demo", kind=KIND_ADDON, path=tmp_path / "demo", is_dir=True
        )
        summary = imp.import_all([plugin], {"demo": True})

        copied.assert_not_called()
        assert summary.imported == 0
        assert summary.failed == 1
        assert summary.items[0].message == "no profile dir"

    def test_a_real_path_still_passes_through(self, monkeypatch):
        bpy = MagicMock()
        bpy.utils.user_resource.return_value = r"C:\Users\raj\AppData\Roaming\Mixar"
        monkeypatch.setattr(imp, "bpy", bpy)
        assert str(imp.mixar_addons_dir()).endswith("Mixar")
