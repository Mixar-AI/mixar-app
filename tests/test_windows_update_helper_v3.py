# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Windows update helper v3: nothing looked up by name, the signer pinned.

The helper runs from the staging directory, which every local account can
write to, and cmd.exe looks a bare program name up in the current directory
first — so every tool is invoked by its System32 path, delayed expansion is
forced off (it would strip the ``!`` of ``/qb!``), and the pre-install
re-verify requires the exact certificate the app verified.
"""

import ntpath
import re
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

from mixar.modules.common.updates.core import (
    app_paths,
    install_flow,
    installer,
    verify,
    win_installer,
)
from mixar.modules.common.updates.core.state import get_update_state

INSTALL_DIR = r"C:\Program Files\Mixar"
THUMBPRINT = "0123456789abcdef0123456789ABCDEF01234567"


def _script(**overrides):
    kwargs = dict(
        installer_path=r"C:\ProgramData\Mixar\Updates\Mixar-3.4.0.msi",
        staging_dir=r"C:\ProgramData\Mixar\Updates",
        version="3.4.0",
        pid=4242,
        relaunch_candidates=[INSTALL_DIR + r"\mixar-launcher.exe"],
        require_signature=True,
        signer_thumbprint=THUMBPRINT,
        install_dir=INSTALL_DIR,
        system_dir=r"C:\Windows\System32",
    )
    kwargs.update(overrides)
    return win_installer.build_script(**kwargs)


_TOOL = re.compile(r"(?i)(?<![\w.-])(powershell|tasklist|find|ping|msiexec|cmd)(\.exe)?\b")


def _invocations(script):
    """``(tool, text before it)`` for every tool named on a command line."""
    found = []
    for line in script.splitlines():
        words = line.strip().lower()
        if words.startswith(("rem ", "echo ", ":")):
            continue
        found += [(m.group(1).lower(), line[:m.start()]) for m in _TOOL.finditer(line)]
    return found


@pytest.mark.parametrize("require_signature", [True, False])
def test_every_tool_is_invoked_by_absolute_path(require_signature):
    script = _script(require_signature=require_signature)
    invoked = _invocations(script)

    assert {tool for tool, _ in invoked} >= {"tasklist", "find", "ping", "msiexec"}
    for tool, before in invoked:
        assert before.endswith("\\"), (tool, before)  # %SYS32%\tool.exe, never bare
    assert 'set "SYS32=C:\\Windows\\System32"' in script
    assert 'set "PWSH=%SYS32%\\WindowsPowerShell\\v1.0\\powershell.exe"' in script
    # Every PowerShell call goes through that absolute path.
    assert script.count(' -Command "') == script.count('"%PWSH%" -NoProfile')
    assert "Start-Process -FilePath ($env:SYS32+'\\msiexec.exe')" in win_installer._PS_INSTALL


@pytest.mark.parametrize("system_root, expected", [
    (r"C:\Windows", r"C:\Windows\System32"),
    (r"D:\WINNT", r"D:\WINNT\System32"),
    (r"C:\My Windows", r"C:\Windows\System32"),   # would need quotes in the pipe
    (r"C:\Win&dows", r"C:\Windows\System32"),
    ("", r"C:\Windows\System32"),
])
def test_system_dir_never_needs_quoting(monkeypatch, system_root, expected):
    monkeypatch.setenv("SystemRoot", system_root)

    assert app_paths.windows_system_dir() == expected


def test_pid_wait_pipe_is_unquoted():
    # cmd re-parses each side of a pipe in a child shell; a mis-parse reads
    # as "Mixar exited" and installs over the running app.
    pipe = next(line for line in _script().splitlines() if "tasklist.exe" in line)

    assert pipe.startswith("%SYS32%\\tasklist.exe ")
    assert "| %SYS32%\\find.exe " in pipe
    assert '"%SYS32%' not in pipe


def test_delayed_expansion_is_forced_off():
    first = _script().splitlines()[:3]
    assert "setlocal enableextensions disabledelayedexpansion" in first


def test_a_missing_powershell_falls_back_to_msiexec():
    script = _script()
    install = script[script.index("rem ---- install"):script.index(":installed")]

    assert 'if not exist "%PWSH%" goto nopowershell' in install
    assert 'if not "%INSTALL_EXIT%"=="9009" goto installed' in install
    fallback = install[install.index(":nopowershell"):]
    assert '"%SYS32%\\msiexec.exe" /i "%MSI%" /qb!' in fallback


def test_the_signer_is_pinned_only_when_the_signature_is_rechecked():
    pinned = _script()
    assert f'set "SIGNER={THUMBPRINT.upper()}"' in pinned
    assert "SignerCertificate.Thumbprint -ne $env:SIGNER" in pinned
    assert "$s.Status -ne 'Valid'" in pinned
    assert pinned.index('set "SIGNER=') < pinned.index("Get-AuthenticodeSignature")

    unsigned = _script(require_signature=False)
    assert "SIGNER" not in unsigned and "Thumbprint" not in unsigned


def test_a_helper_without_a_thumbprint_keeps_the_valid_only_check():
    script = _script(signer_thumbprint="")
    assert 'set "SIGNER="\n' in script
    # An empty %SIGNER% skips the pin inside the snippet itself.
    assert "if($env:SIGNER -and " in win_installer._PS_VERIFY


def test_the_thumbprint_is_reduced_to_hex():
    script = _script(signer_thumbprint='ab:cd 12"&|^%!')
    assert 'set "SIGNER=ABCD12"' in script


def test_the_previous_msi_log_is_kept_before_the_installer_runs():
    script = _script()
    rotate = 'if exist "%MSILOG%" move /y "%MSILOG%" "%MSIPREVLOG%" >nul 2>&1'

    assert rotate in script
    assert 'set "MSIPREVLOG=C:\\ProgramData\\Mixar\\Updates' in script
    assert script.index(":signature_ok") < script.index(rotate)
    assert script.index(rotate) < script.index("-Verb RunAs")
    assert script.index(rotate) < script.index(":nopowershell")


def test_the_helper_is_started_by_absolute_cmd_without_autorun(monkeypatch, tmp_path):
    started = []

    def popen(argv, **kwargs):
        started.append(argv)
        return MagicMock(pid=1)

    monkeypatch.setattr(win_installer.subprocess, "Popen", popen)
    monkeypatch.setenv("SystemRoot", r"D:\Win")

    win_installer.launch(
        installer_path=str(tmp_path / "Mixar-3.4.0.msi"), staging_dir=str(tmp_path),
        version="3.4.0", relaunch_candidates=[], require_signature=True,
        signer_thumbprint=THUMBPRINT,
    )

    argv = started[0]
    assert argv[:3] == [r"D:\Win\System32\cmd.exe", "/d", "/c"]
    assert ntpath.isabs(argv[0])
    script = Path(argv[3]).read_text(encoding="cp1252")
    assert 'set "SYS32=D:\\Win\\System32"' in script
    assert f'set "SIGNER={THUMBPRINT.upper()}"' in script


def test_begin_install_hands_the_signer_to_the_helper(monkeypatch):
    launched = MagicMock()
    monkeypatch.setattr(installer.os, "name", "nt")
    monkeypatch.setattr(win_installer, "launch", launched)
    location = app_paths.InstallLocation(INSTALL_DIR, True, "", relaunch_candidates=["x"])

    installer.begin_install(
        installer_path="a.msi", staging_dir="s", version="3.4.0",
        eligibility=installer.Eligibility(True, location=location), verified=True,
        signer_thumbprint=THUMBPRINT,
    )

    assert launched.call_args.kwargs["signer_thumbprint"] == THUMBPRINT


# ---------------------------------------------------------------------------
# The app side: verify.py yields the certificate, state carries it
# ---------------------------------------------------------------------------


def _authenticode(results):
    def run(argv):
        assert ntpath.isabs(argv[0]) and argv[0].lower().endswith(
            "\\windowspowershell\\v1.0\\powershell.exe"), argv[0]
        # Rendered from a str.format template: PowerShell sees single braces.
        assert "if($s.SignerCertificate){Write-Output" in argv[-1]
        assert argv[-1].endswith("Thumbprint}")
        return results[argv[-1].split("-LiteralPath ")[1].split(";")[0]]
    return run


def test_verify_returns_the_signer_thumbprint(monkeypatch):
    """Through the real _authenticode: its template used to raise KeyError on
    PowerShell's braces, so every Windows check ended UNVERIFIED."""
    subject = "CN=Adeveda Enterprises Private Limited"
    monkeypatch.setattr(verify, "_run", _authenticode({
        "'app.exe'": (0, f"Valid\n{subject}\nAAAA"),
        "'new.msi'": (0, f"Valid\n{subject}\n{THUMBPRINT}"),
        "'evil.msi'": (0, f"Valid\nCN=Someone Else\n{'F' * 40}"),
    }))

    assert verify._verify_windows("new.msi", "app.exe") == (
        verify.VERIFIED, subject, THUMBPRINT)
    verdict, _, thumbprint = verify._verify_windows("evil.msi", "app.exe")
    assert (verdict, thumbprint) == (verify.REJECTED, "")


def test_state_keeps_the_thumbprint_only_for_a_verified_installer(tmp_path):
    state = get_update_state()
    state.set_idle()
    state.set_ready("a.msi", True, THUMBPRINT)
    assert state.signer_thumbprint == THUMBPRINT
    state.set_ready("a.msi", False, THUMBPRINT)
    assert state.signer_thumbprint == ""
    state.set_idle()
    assert state.signer_thumbprint == ""


def test_an_aborted_quit_keeps_the_pinned_signer(monkeypatch):
    state = get_update_state()
    state.set_idle()
    state.set_ready("a.msi", True, THUMBPRINT)
    state.set_installing()
    monkeypatch.setattr(install_flow, "_helper_proc", None)
    from mixar.modules.common.updates.core import toasts
    monkeypatch.setattr(toasts, "push_install_aborted_toast", MagicMock())

    install_flow._abort_pending_install()

    assert (state.signature_verified, state.signer_thumbprint) == (True, THUMBPRINT)
    state.set_idle()
