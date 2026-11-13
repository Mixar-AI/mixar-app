# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The previous update attempt, judged on the next launch.

Pins how a helper result becomes an outcome + failure_reason, the toast
that explains it, and the content-free ``update.install_result`` payload.
The helper itself only runs on Windows; these are its recorded outcomes.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

for _name in ("blf", "gpu", "gpu.state", "gpu.shader", "gpu_extras", "gpu_extras.batch"):
    sys.modules.setdefault(_name, MagicMock(name=_name))

sys.modules.setdefault(
    "mixar.modules.common.utils.mixie_space_utils",
    MagicMock(name="mixie_space_utils"),
)

import pytest

from mixar.modules.common.notifications.store import get_notification_store
from mixar.modules.common.updates.constants import UPDATE_NOTIFICATION_ID
from mixar.modules.common.updates.core import installer, result_report, toasts

INSTALL_DIR = r"C:\Program Files\Mixar"
INSTALLED_EXE = INSTALL_DIR + r"\mixar.exe"
PORTABLE_EXE = r"D:\Tools\Mixar-portable\mixar.exe"


def _result(**fields):
    record = {"version": "3.4.0", "stage": "install", "exit": "0"}
    record.update(fields)
    return record


def setup_function(_fn):
    get_notification_store().clear_all()


def _toast():
    for item in get_notification_store().get_visible():
        if item.id == UPDATE_NOTIFICATION_ID:
            return item
    raise AssertionError("update toast not found in store")


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("result, running, binary, outcome, reason", [
    (_result(), "3.4.0", INSTALLED_EXE, "success", ""),
    # The installer's 0 is not proof: the version must be known and match.
    (_result(), "", INSTALLED_EXE, "no_effect", "running_version_unknown"),
    (_result(), "3.3.6", INSTALLED_EXE, "no_effect", "unknown"),
    (_result(install_location=INSTALL_DIR, installed_version="3.4.0"),
     "3.3.6", PORTABLE_EXE, "no_effect", "old_copy_relaunched"),
    (_result(install_location=INSTALL_DIR, installed_version="3.3.6"),
     "3.3.6", INSTALLED_EXE, "no_effect", "msi_not_upgraded"),
    # 3010 with the old build back: the held files are replaced at reboot.
    (_result(exit="3010"), "3.3.6", INSTALLED_EXE, "pending_reboot", "files_pending_reboot"),
    # 3010 with the new build running: only old copies wait for the reboot.
    (_result(exit="3010"), "3.4.0", INSTALLED_EXE, "success", ""),
    (_result(exit="1602"), "3.3.6", INSTALLED_EXE, "failed", "uac_declined"),
    (_result(exit="1618"), "3.3.6", INSTALLED_EXE, "failed", "another_install"),
    (_result(exit="1603", msi_error="1925"), "3.3.6", INSTALLED_EXE, "failed", "msi_error"),
    (_result(exit="1"), "3.3.6", INSTALLED_EXE, "failed", "msi_error"),
    (_result(stage="locked", exit="locked", locks="mixar.exe,python.exe"),
     "3.3.6", INSTALLED_EXE, "failed", "locked"),
    (_result(stage="wait", exit="timeout"), "3.3.6", INSTALLED_EXE, "failed", "timeout"),
    (_result(stage="verify", exit="signature"), "3.3.6", INSTALLED_EXE, "failed", "signature"),
    (_result(stage="swap", exit="1"), "3.3.6", "", "failed", "swap"),
])
def test_results_classify_by_cause(result, running, binary, outcome, reason):
    verdict = installer.classify_result(result, running, binary)

    assert (verdict["outcome"], verdict["failure_reason"]) == (outcome, reason)


@pytest.mark.parametrize("result, running, pending, outcome, reason", [
    # A held file still queued for the reboot: the new exe may run an old DLL.
    (_result(exit="3010"), "3.4.0", True, "pending_reboot", "files_pending_reboot"),
    (_result(exit="3010"), "3.4.0", False, "success", ""),
    (_result(exit="3010"), "3.3.6", True, "pending_reboot", "files_pending_reboot"),
    # Exit 0 is judged by the version alone.
    (_result(), "3.4.0", True, "success", ""),
    (_result(), "3.3.6", True, "no_effect", "unknown"),
    (_result(exit="1603"), "3.3.6", True, "failed", "msi_error"),
])
def test_queued_reboot_renames_decide_a_3010(result, running, pending, outcome, reason):
    verdict = installer.classify_result(
        result, running, INSTALLED_EXE, files_pending_reboot=pending)

    assert (verdict["outcome"], verdict["failure_reason"]) == (outcome, reason)


def test_relaunch_match_is_only_known_with_a_registered_location():
    assert installer.classify_result(_result(), "3.4.0", INSTALLED_EXE)[
        "relaunch_matched"] is None
    located = _result(install_location=INSTALL_DIR)
    assert installer.classify_result(located, "3.4.0", INSTALLED_EXE)[
        "relaunch_matched"] is True
    assert installer.classify_result(located, "3.4.0", PORTABLE_EXE)[
        "relaunch_matched"] is False


def test_a_bom_where_powershell_started_appending_is_ignored(tmp_path):
    """PowerShell 5.1's Add-Content -Encoding UTF8 may write a BOM after cmd's lines."""
    (tmp_path / "update-result.txt").write_bytes(
        b"version=3.4.0\r\nstage=install\r\nexit=0\r\nhelper_version=3\r\n"
        + "\ufeffinstalled_version=3.4.0\r\ninstall_location=C:\\Program Files\\Mixar\r\n"
          "relaunch_kind=registry\r\n".encode("utf-8"))

    result = installer.consume_result(str(tmp_path))

    assert result["installed_version"] == "3.4.0"
    assert "\ufeffinstalled_version" not in result
    assert result["relaunch_kind"] == "registry"


def test_versions_compare_numerically():
    assert installer.classify_result(_result(version="3.4"), "3.4.0")["outcome"] == "success"
    assert installer.classify_result(
        _result(installed_version="3.4", install_location=INSTALL_DIR),
        "3.3.6", INSTALLED_EXE,
    )["failure_reason"] == "unknown"


# ---------------------------------------------------------------------------
# Toasts
# ---------------------------------------------------------------------------


def _report(monkeypatch, result, running, binary=INSTALLED_EXE):
    import mixar.modules.common.updates.core.install_flow as install_flow
    import mixar.modules.common.updates.core.update_checker as update_checker

    monkeypatch.setattr(install_flow, "read_previous_result", lambda: result)
    monkeypatch.setattr(update_checker, "get_runtime_version", lambda: running)
    monkeypatch.setattr(result_report, "_running_binary", lambda: binary)
    monkeypatch.setattr(result_report, "_install_kind", lambda: "msi")
    with patch.object(result_report, "_capture_result"):
        toasts.report_previous_update_result()
    return _toast()


def test_pending_reboot_asks_for_a_windows_restart(monkeypatch):
    item = _report(monkeypatch, _result(exit="3010"), "3.3.6")

    assert item.title == "Restart Windows to finish updating"
    assert item.type.value == "warning"
    assert not item.actions


def _pending_registry(monkeypatch, read):
    from mixar.modules.common.updates.core import pending_renames

    monkeypatch.setattr(pending_renames, "_on_windows", lambda: True)
    monkeypatch.setattr(pending_renames, "read_pending_renames", read)


def test_a_3010_with_a_rename_queued_in_the_install_asks_for_a_restart(monkeypatch):
    held = [(r"C:\Program Files\Mixar\~DF1A2B.tmp", r"C:\Program Files\Mixar\a.dll")]
    _pending_registry(monkeypatch, lambda: held)

    # Judged on the helper's recorded location, else the running binary's folder.
    for result in (_result(exit="3010", install_location=INSTALL_DIR), _result(exit="3010")):
        item = _report(monkeypatch, result, "3.4.0")
        assert item.title == "Restart Windows to finish updating"
        get_notification_store().clear_all()

    other = [(r"C:\Config.Msi\3a5f2e.rbf", ""), (r"C:\Other\a.tmp", r"C:\Other\a.dll")]
    _pending_registry(monkeypatch, lambda: other)
    assert _report(monkeypatch, _result(exit="3010"), "3.4.0").title == "Updated to Mixar 3.4.0"


def test_an_unreadable_rename_queue_keeps_the_success(monkeypatch):
    def unreadable():
        raise PermissionError(5, "Access is denied")

    _pending_registry(monkeypatch, unreadable)

    assert _report(monkeypatch, _result(exit="3010"), "3.4.0").title == "Updated to Mixar 3.4.0"


def test_only_a_3010_reads_the_rename_queue(monkeypatch):
    read = MagicMock(return_value=[(INSTALLED_EXE, "")])
    _pending_registry(monkeypatch, read)

    assert _report(monkeypatch, _result(), "3.4.0").title == "Updated to Mixar 3.4.0"
    read.assert_not_called()


def test_empty_running_version_is_not_reported_as_success(monkeypatch):
    item = _report(monkeypatch, _result(), "")

    assert item.title == "Update didn't take effect"
    assert "could not be confirmed" in item.body


def test_portable_copy_relaunch_says_where_to_open_mixar(monkeypatch):
    item = _report(
        monkeypatch, _result(install_location=INSTALL_DIR, installed_version="3.4.0"),
        "3.3.6", PORTABLE_EXE,
    )

    assert item.title == "Update didn't take effect"
    assert "Start menu" in item.body
    assert [a.label for a in item.actions] == ["Download"]


@pytest.mark.parametrize("result, phrase", [
    (_result(stage="locked", exit="locked", locks="mixar.exe,python.exe"),
     "mixar.exe, python.exe"),
    (_result(stage="locked", exit="locked"), "Mixar connector"),
    (_result(exit="1602"), "administrator prompt"),
    (_result(exit="1618"), "Another installation"),
    (_result(exit="1603", msi_error="1925"), "error 1925"),
    (_result(exit="1603"), "error 1603"),
])
def test_failures_carry_specific_advice_and_the_download_link(monkeypatch, result, phrase):
    item = _report(monkeypatch, result, "3.3.6")

    assert item.title == "Update was not installed"
    assert phrase in item.body
    assert "downloads page" in item.body
    assert [a.label for a in item.actions] == ["Download"]


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------


def _captured(monkeypatch, result, running="3.3.6", binary=INSTALLED_EXE):
    import mixar.modules.common.updates.core.install_flow as install_flow
    import mixar.modules.common.updates.core.update_checker as update_checker
    from mixar.modules.common.analytics import update_events

    monkeypatch.setattr(install_flow, "read_previous_result", lambda: result)
    monkeypatch.setattr(update_checker, "get_runtime_version", lambda: running)
    monkeypatch.setattr(result_report, "_running_binary", lambda: binary)
    monkeypatch.setattr(result_report, "_install_kind", lambda: "msi")
    with patch.object(update_events, "capture") as captured:
        toasts.report_previous_update_result()
    assert captured.call_args.args[0] == "update.install_result"
    return captured.call_args.args[1]


def test_result_event_carries_the_diagnostics(monkeypatch):
    props = _captured(monkeypatch, _result(
        stage="locked", exit="locked", locks="mixar.exe,python.exe,../evil",
        from_version="3.3.6", attempt_id="a" * 32, helper_version="2",
        wait_s="63", install_location=INSTALL_DIR, installed_version="3.3.6",
        relaunch=INSTALLED_EXE, relaunch_kind="registry",
    ))

    assert props == {
        "target_version": "3.4.0", "outcome": "failed", "stage": "locked",
        "from_version": "3.3.6", "running_version": "3.3.6", "exit_code": None,
        "msi_error": None, "failure_reason": "locked", "attempt_id": "a" * 32,
        "helper_version": 2, "install_kind": "msi", "installed_version": "3.3.6",
        "relaunch_matched": True, "relaunch_kind": "registry",
        "locking_processes": "mixar.exe,python.exe,..evil", "wait_s": 63,
        # No trigger recorded: a helper from before install-on-quit.
        "trigger": "click",
        # Helper v7 / #2079 fields: unknown here (an older helper, a macOS host).
        "install_scope": None, "moved_from_program_files": None,
        "msi_refusal": None, "elevation": None,
        # Helper v8: where the installer put Mixar and why.
        "install_decision": None, "install_decision_reason": None,
    }
    # Paths recorded by the helper stay on the machine.
    assert not any("\\" in str(value) for value in props.values())


def test_result_event_names_the_installer_decision(monkeypatch):
    """Helper v8 copies MIXAR_SCOPE_ACTION / _REASON from the MSI log (#2079):
    whether Mixar moved, stayed or was updated in place, and why."""
    props = _captured(monkeypatch, _result(exit="0", scope_action="in_place",
                                           scope_reason="path_policy"))
    assert (props["install_decision"], props["install_decision_reason"]) == (
        "in_place", "path_policy")
    # Anything else in the file (a path, a newer installer's name) is dropped.
    props = _captured(monkeypatch, _result(exit="0", scope_action="teleport",
                                           scope_reason="C:\\Users\\ana"))
    assert (props["install_decision"], props["install_decision_reason"]) == (None, None)


def test_result_event_from_the_old_helper(monkeypatch):
    props = _captured(monkeypatch, _result(exit="3010"))

    assert props["outcome"] == "pending_reboot"
    assert props["exit_code"] == 3010
    assert props["helper_version"] == 1
    assert props["relaunch_matched"] is None


def test_result_event_fits_the_backend_property_cap():
    """Backend telemetry refuses > 32 properties; common ones come first."""
    import importlib

    capture_module = importlib.import_module("mixar.modules.common.analytics.capture")
    from mixar.modules.common.analytics.constants import MAX_PROPERTIES
    from mixar.modules.common.analytics.update_events import RESULT_DETAIL_KEYS

    common = capture_module._common_properties(MagicMock())
    assert len(common) + 3 + len(RESULT_DETAIL_KEYS) <= MAX_PROPERTIES == 32


def test_unknown_detail_keys_never_ship():
    from mixar.modules.common.analytics import update_events

    with patch.object(update_events, "capture") as captured:
        update_events.capture_update_result(
            "3.4.0", "failed", "install",
            details={"install_location": INSTALL_DIR, "exit_code": 1603},
        )
    assert captured.call_args.args[1] == {
        "target_version": "3.4.0", "outcome": "failed", "stage": "install",
        "exit_code": 1603,
    }
