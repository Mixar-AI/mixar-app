# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Windows self-update: who may self-install, what blocks it, what the
helper records.

The helper runs after Mixar is gone, so its text is the contract: the
install-directory lock wait, the result fields, exit-code propagation and
the registry-first relaunch. Eligibility and the pre-quit process check are
pure functions over canned registry rows and process tables.
"""

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

sys.modules.setdefault(
    "mixar.modules.common.utils.mixie_space_utils",
    MagicMock(name="mixie_space_utils"),
)

import pytest

from mixar.modules.common.updates.constants import InstallState
from mixar.modules.common.updates.core import (
    app_paths,
    install_flow,
    install_gate,
    installer,
    staging,
    win_installer,
    win_processes,
)
from mixar.modules.common.updates.core.state import UpdateInfo, get_update_state

INSTALL_DIR = r"C:\Program Files\Mixar"
DEFAULT_DIR = r"C:\Program Files\Mixar"


def _script(**overrides):
    kwargs = dict(
        installer_path=r"C:\ProgramData\Mixar\Updates\Mixar-3.4.0.msi",
        staging_dir=r"C:\ProgramData\Mixar\Updates",
        version="3.4.0",
        pid=4242,
        relaunch_candidates=[INSTALL_DIR + r"\mixar-launcher.exe"],
        require_signature=False,
        install_dir=INSTALL_DIR,
        from_version="3.3.6",
        attempt_id="0123abcd",
    )
    kwargs.update(overrides)
    return win_installer.build_script(**kwargs)


# ---------------------------------------------------------------------------
# Eligibility: only the copy Windows Installer registered self-installs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("install_dir, installs, kind", [
    (INSTALL_DIR, [], "portable"),
    (INSTALL_DIR, [{"version": "3.3.6", "location": INSTALL_DIR + "\\"}], "msi"),
    (r"c:\program files\mixar", [{"version": "3.3.6", "location": INSTALL_DIR}], "msi"),
    (r"D:\Mixar-portable", [{"version": "3.3.6", "location": INSTALL_DIR}], "portable"),
    (r"C:\Program Files\Mixar Old", [{"version": "3.3.6", "location": INSTALL_DIR}],
     "portable"),
    # MSIs built before ARPINSTALLLOCATION register no location: only the
    # default directory can be assumed to be theirs.
    (DEFAULT_DIR, [{"version": "3.3.6", "location": ""}], "msi"),
    (r"D:\Apps\Mixar", [{"version": "3.3.6", "location": ""}], "portable"),
])
def test_only_the_registered_install_counts(install_dir, installs, kind):
    assert app_paths.classify_windows_install(install_dir, installs, DEFAULT_DIR)[0] == kind


def _windows(monkeypatch, binary, installs):
    monkeypatch.setattr(app_paths, "_binary_path", lambda: binary)
    monkeypatch.setattr(app_paths, "_default_windows_dir", lambda: DEFAULT_DIR)
    if isinstance(installs, Exception):
        def _raise():
            raise installs
        monkeypatch.setattr(app_paths, "windows_msi_installs", _raise)
    else:
        monkeypatch.setattr(app_paths, "windows_msi_installs", lambda: installs)
    monkeypatch.setattr(app_paths.os.path, "dirname", lambda p: p.rsplit("\\", 1)[0])
    monkeypatch.setattr(app_paths.os.path, "abspath", lambda p: p)
    return app_paths._windows_location()


def test_unregistered_copy_goes_to_the_browser(monkeypatch):
    location = _windows(
        monkeypatch, r"D:\Mixar-portable\mixar.exe",
        [{"version": "3.3.6", "location": INSTALL_DIR}],
    )
    monkeypatch.setattr(installer, "_platform_key", lambda: "windows")
    monkeypatch.setattr(installer.app_paths, "get_install_location", lambda: location)

    verdict = installer.check_eligibility(UpdateInfo(
        latest_version="3.4.0", current_version="3.3.6",
        download_url="https://cdn.example.com/Mixar-3.4.0.msi",
        download_sha256="a" * 64, installer_type="msi",
    ))

    assert location.kind == "portable"
    assert not verdict
    assert "installer" in verdict.reason


def test_registered_copy_is_eligible(monkeypatch):
    location = _windows(
        monkeypatch, INSTALL_DIR + r"\mixar.exe",
        [{"version": "3.3.6", "location": INSTALL_DIR}],
    )
    assert (location.kind, location.writable) == ("msi", True)


def test_unreadable_registry_keeps_the_old_behaviour(monkeypatch):
    location = _windows(monkeypatch, r"D:\Elsewhere\mixar.exe", OSError("denied"))
    assert (location.kind, location.writable) == ("unknown", True)


# ---------------------------------------------------------------------------
# Pre-quit: other processes running from the install directory
# ---------------------------------------------------------------------------


def _proc(pid, parent, name, path="", window=False):
    # Creation time = pid: every parent here is older than its children.
    return {"pid": pid, "ppid": parent, "name": name, "path": path,
            "created": pid, "has_window": window}


TABLE = [
    _proc(100, 1, "mixar.exe", INSTALL_DIR + r"\mixar.exe", window=True),  # us
    _proc(101, 100, "mixar.exe", INSTALL_DIR + r"\mixar.exe"),         # our backfill
    _proc(200, 1, "mixar-launcher.exe", INSTALL_DIR + r"\mixar-launcher.exe"),
    _proc(201, 200, "mixar.exe", INSTALL_DIR + r"\mixar.exe", window=True),  # other window
    _proc(300, 1, "claude.exe", r"C:\Users\u\AppData\Local\AnthropicClaude\claude.exe"),
    _proc(301, 300, "cmd.exe", r"C:\Windows\System32\cmd.exe"),
    _proc(302, 301, "python.exe", INSTALL_DIR + r"\5.0\python\bin\python.exe"),
    _proc(400, 1, "explorer.exe", r"C:\Windows\explorer.exe"),
    _proc(500, 9999, "python.exe", INSTALL_DIR + r"\5.0\python\bin\python.exe"),  # orphan
    _proc(600, 1, "Code.exe", r"C:\Program Files\Mixar Tools\Code.exe"),  # prefix only
]


def test_holders_are_classified_by_what_the_user_can_do():
    holders = win_processes.classify(TABLE, INSTALL_DIR, own_pid=100)
    assert [(h.kind, h.name, h.pid) for h in holders] == [
        (win_processes.BACKGROUND, "mixar.exe", 101),           # our own work
        (win_processes.BACKGROUND, "mixar-launcher.exe", 200),  # windowless
        (win_processes.MIXAR_WINDOW, "Mixar", 201),
        (win_processes.CONNECTOR, "claude", 302),
        # Its AI app is gone: nothing to close, so the update ends it.
        (win_processes.ABANDONED_CONNECTOR, "python.exe", 500),
    ]


def test_process_check_failure_never_blocks(monkeypatch):
    def _boom():
        raise OSError("no powershell")
    monkeypatch.setattr(win_processes, "_process_table", _boom)
    assert win_processes.blocking_apps(INSTALL_DIR, 100) == []


def _ready(tmp_path):
    installer_file = tmp_path / "Mixar-3.4.0.msi"
    installer_file.write_bytes(b"msi")
    state = get_update_state()
    state.set_idle()
    state.set_available(UpdateInfo(
        latest_version="3.4.0", current_version="3.3.6",
        download_url="https://cdn.example.com/Mixar-3.4.0.msi",
        download_sha256="a" * 64, installer_type="msi",
    ))
    state.set_ready(str(installer_file), True)
    return state


def test_apply_stops_and_names_the_apps_holding_the_install(monkeypatch, tmp_path):
    state = _ready(tmp_path)
    location = app_paths.InstallLocation(INSTALL_DIR, True, "", kind="msi")
    monkeypatch.setattr(installer, "check_eligibility",
                        lambda info: installer.Eligibility(True, location=location, extension=".msi"))
    # A live connector is ended first; one that survives is what the user is
    # asked to close (named after its AI app).
    claude = win_processes.Holder(win_processes.CONNECTOR, "claude", 302, 302)
    monkeypatch.setattr(install_gate, "_is_windows", lambda: True)
    monkeypatch.setattr(install_gate, "_holders", lambda install_dir: [claude])
    monkeypatch.setattr(win_processes, "terminate", lambda holder: False)
    began = MagicMock()
    monkeypatch.setattr(installer, "begin_install", began)
    shown = MagicMock()
    from mixar.modules.common.updates.core import toasts
    monkeypatch.setattr(toasts, "push_close_apps_toast", shown)

    started, message = install_flow.apply_and_restart()

    assert (started, message) == (False, install_flow.BLOCKED_BY_OTHER_APPS)
    shown.assert_called_once_with([claude])
    began.assert_not_called()
    assert state.install_state is InstallState.READY


def test_apply_passes_the_attempt_to_the_helper(monkeypatch, tmp_path):
    _ready(tmp_path)
    location = app_paths.InstallLocation(INSTALL_DIR, True, "", kind="msi")
    monkeypatch.setattr(installer, "check_eligibility",
                        lambda info: installer.Eligibility(True, location=location, extension=".msi"))
    monkeypatch.setattr(install_gate, "_is_windows", lambda: True)
    monkeypatch.setattr(install_gate, "_holders", lambda install_dir: [])
    began = MagicMock()
    monkeypatch.setattr(installer, "begin_install", began)
    import mixar.modules.common.updates.core.update_checker as update_checker
    monkeypatch.setattr(update_checker, "get_runtime_version", lambda: "3.3.6")

    started, _ = install_flow.apply_and_restart()

    kwargs = began.call_args.kwargs
    assert started is True
    assert kwargs["from_version"] == "3.3.6"
    assert len(kwargs["attempt_id"]) == 32
    install_flow._helper_proc = None
    get_update_state().set_idle()


def test_close_apps_toast_names_each_app():
    from mixar.modules.common.notifications.store import get_notification_store
    from mixar.modules.common.updates.constants import UPDATE_NOTIFICATION_ID
    from mixar.modules.common.updates.core import toasts

    get_notification_store().clear_all()
    toasts.push_close_apps_toast([
        (win_processes.MIXAR_WINDOW, "Mixar"),
        (win_processes.CONNECTOR, "claude"),
        (win_processes.CONNECTOR, ""),
    ])
    item = next(i for i in get_notification_store().get_visible()
                if i.id == UPDATE_NOTIFICATION_ID)

    assert item.title == "Close other apps to update"
    assert "Another Mixar window" in item.body
    assert "claude (using the Mixar connector)" in item.body
    assert "An AI app using the Mixar connector" in item.body
    assert [a.label for a in item.actions] == ["Restart & Update"]


def test_operator_keeps_the_close_apps_toast():
    source = (SCRIPTS / "mixar" / "modules" / "common" / "updates" / "ui"
              / "operators.py").read_text(encoding="utf-8")
    block = source[source.index("started, message = apply_and_restart()"):]
    assert block.index("BLOCKED_BY_OTHER_APPS") < block.index("refresh_update_toast()")


# ---------------------------------------------------------------------------
# The helper script
# ---------------------------------------------------------------------------


def test_helper_waits_for_processes_in_the_install_dir_without_closing_them():
    script = _script()
    lock = script[script.index(":lockloop"):script.index(":unlocked")]

    assert f'set "INSTALLDIR={INSTALL_DIR}"' in script
    assert "Win32_Process" in lock and "ExecutablePath" in lock
    assert 'if not "%ERRORLEVEL%"=="3" goto unlocked' in lock
    assert "if %LOCKWAIT% GEQ 60 goto locked" in lock
    assert "call :result locked locked" in lock
    assert 'type "%LOCKS%" >>"%RESULT%"' in lock
    # The wait never force-closes anything (only the connector end step
    # before it does, and only connector pythons — helper v4).
    for verb in ("taskkill", "Stop-Process", ".Kill(", "Terminate"):
        assert verb not in lock
        assert verb not in win_installer._PS_LOCKS
        assert verb not in win_installer._PS_INSTALL
        assert verb not in win_installer._PS_FINISH
    # Basenames only reach the result file.
    assert "$_.Name -replace" in win_installer._PS_LOCKS
    assert "ExecutablePath -join" not in win_installer._PS_LOCKS
    # The lock wait runs before the installer, after the PID wait.
    assert script.index(":gone") < script.index(":lockloop") < script.index("-Verb RunAs")


def test_helper_result_carries_the_attempt_fields():
    script = _script()
    record = script[script.index(":result\n"):]

    for line in ("version=%VERSION%", "stage=%~1", "exit=%~2",
                 "from_version=%FROM_VERSION%", "attempt_id=%ATTEMPT%",
                 "helper_version=4", "wait_s=%WAITED%"):
        assert f'echo {line}' in record, line
    assert 'set "FROM_VERSION=3.3.6"' in script
    assert 'set "ATTEMPT=0123abcd"' in script


def test_helper_records_the_registry_and_relaunches_from_it_first():
    finish = win_installer._PS_FINISH

    assert "DisplayVersion" in finish and "InstallLocation" in finish
    assert "installed_version=" in finish and "install_location=" in finish
    assert "WOW6432Node" in finish and "HKCU:" in finish
    assert "msi_error=" in finish and "Error (\\d{4})\\." in finish
    # Registry candidates are queued before the guessed ones.
    assert finish.index("'registry'") < finish.index("'candidate'")
    assert "relaunch_kind=" in finish
    script = _script()
    finish_block = script[script.index(":finish"):script.index(":relaunched")]
    assert 'if "%ERRORLEVEL%"=="0" goto relaunched' in finish_block
    # PowerShell unavailable -> the batch candidates still bring Mixar back.
    assert 'start "" "C:\\Program Files\\Mixar\\mixar-launcher.exe"' in finish_block
    assert "relaunch_kind=fallback" in finish_block


def test_helper_exit_status_is_the_installers():
    script = _script()

    assert script.count("exit /b %INSTALL_EXIT%") == 2
    assert 'set "INSTALL_EXIT=1"' in script.split(":waitloop")[0]
    # A failed launch is never exit 0.
    assert "if($null -eq $p -or $null -eq $p.ExitCode){exit 1}" in win_installer._PS_INSTALL
    assert "exit 1602" in win_installer._PS_INSTALL


@pytest.mark.parametrize("name", ["_PS_INSTALL", "_PS_VERIFY", "_PS_END_CONNECTORS", "_PS_LOCKS", "_PS_FINISH"])
def test_powershell_snippets_survive_batch_quoting(name):
    """Embedded in -Command "...": a quote would end the argument and a
    percent sign would be expanded by cmd."""
    snippet = getattr(win_installer, name)
    assert '"' not in snippet and "%" not in snippet
    # "/qb!" is only safe while delayed expansion stays off — explicitly,
    # since a registry DelayedExpansion=1 turns it on for cmd /c.
    assert "setlocal enableextensions disabledelayedexpansion" in _script()
    assert "\r" not in snippet and "\n" not in snippet


def test_unsafe_install_dir_is_refused(tmp_path):
    with pytest.raises(ValueError):
        win_installer.launch(
            installer_path=str(tmp_path / "Mixar-3.4.0.msi"),
            staging_dir=str(tmp_path),
            version="3.4.0",
            relaunch_candidates=[],
            install_dir=r"C:\Mix&ar",
        )


def test_begin_install_hands_the_install_dir_to_the_helper(monkeypatch):
    launched = MagicMock()
    monkeypatch.setattr(installer.os, "name", "nt")
    monkeypatch.setattr(win_installer, "launch", launched)
    location = app_paths.InstallLocation(INSTALL_DIR, True, "", relaunch_candidates=["x"])

    installer.begin_install(
        installer_path="a.msi", staging_dir="s", version="3.4.0",
        eligibility=installer.Eligibility(True, location=location), verified=True,
        from_version="3.3.6", attempt_id="id",
    )

    kwargs = launched.call_args.kwargs
    assert (kwargs["install_dir"], kwargs["from_version"], kwargs["attempt_id"]) == (
        INSTALL_DIR, "3.3.6", "id")


# ---------------------------------------------------------------------------
# Staging keeps an attempt's evidence
# ---------------------------------------------------------------------------


def test_purge_keeps_the_result_until_read_and_the_logs_always(tmp_path):
    resolved = staging.StagingDir(str(tmp_path), True)
    logs = ["msi-install.log", "msi-install.prev.log", "update.log"]
    for name in ["update-result.txt", "Mixar-3.3.9.msi", *logs]:
        (tmp_path / name).write_text(name)

    staging.purge_stale(resolved)
    assert sorted(os.listdir(tmp_path)) == sorted(["update-result.txt", *logs])

    (tmp_path / "update-result.txt").unlink()  # read at startup
    staging.purge_stale(resolved)
    assert sorted(os.listdir(tmp_path)) == logs


def test_msi_install_location_is_left_to_cpack():
    # CPack's generated properties.wxi already sets ARPINSTALLLOCATION from
    # INSTALL_ROOT; a second SetProperty in the template fails light.exe
    # with LGHT0091 (duplicate SetARPINSTALLLOCATION).
    template = (ROOT / "src" / "release" / "windows" / "installer_wix"
                / "WIX.template").read_text(encoding="utf-8")
    assert '<SetProperty Id="ARPINSTALLLOCATION"' not in template
