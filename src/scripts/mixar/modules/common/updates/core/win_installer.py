# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Windows Update Helper

Writes and launches the detached batch script that applies a staged MSI
after Mixar exits.

Design notes, each one a failure this replaces:

- **The helper cannot live in the install directory.**  The MSI replaces
  everything there, so a helper running from it would be deleted (or
  block the upgrade) mid-install.  It runs out of the staging directory,
  driven by ``cmd.exe`` from ``System32``.
- **It waits for our PID, not for a fixed delay.**  Windows Installer
  refuses to replace files that are still open, and a sleep long enough
  to be safe is long enough to feel broken.
- **Then it ends Mixar connectors and waits for everything else running
  from the install directory.**  A file in use is not an error to msiexec:
  it defers the replacement to the next reboot and returns 3010, and the
  relaunch starts the old build.  An AI app respawns its MCP server (our
  ``python.exe``) on its next tool call, so one may appear after the app's
  own pre-quit check; connectors hold no user work and are stale once
  Mixar restarts, so the helper ends them (helper v4) — a python started by
  a Mixar is background work and is left alone.  For anything else the
  helper waits (bounded) and records ``stage=locked`` with the process
  basenames rather than installing; it never closes a window.
- **Elevation is explicit.**  ``Start-Process -Verb RunAs`` raises the UAC
  prompt and reports whether the user accepted, instead of letting
  ``msiexec`` fail with 1925 in the cases where it will not self-elevate.
  Plain ``msiexec`` remains the fallback when PowerShell is unavailable.
- **It never shows a modal installer prompt.**  Under ``/qb!`` a file held
  from outside the install dir (antivirus, a service) stopped the update
  on Restart Manager's files-in-use dialog, twice (#2060). ``/passive``
  keeps the progress bar and closes holders, else replaces at reboot (3010).
- **The app always comes back — from where the MSI installed it.**
  Relaunch runs whatever the installer returned (a declined UAC prompt
  must leave the user with the version they already had), and prefers the
  Uninstall key's ``InstallLocation`` over the guessed candidates, which
  remain the fallback when PowerShell cannot run. An install on quit
  (helper v6, ``RELAUNCHMODE=0``; nothing starts one yet, every Windows
  install needs the UAC prompt) leaves Mixar closed and records
  ``relaunch_kind=skipped`` — unless a launch was turned away meanwhile.
- **The outcome is written down.**  ``update-result.txt`` is the only way
  the relaunched app can tell the user that an update it started did not
  finish.  Beyond ``version``/``stage``/``exit`` it carries the attempt
  id, the version updated from, seconds waited, the registry's
  ``DisplayVersion``/``InstallLocation``, the MSI's first ``Error NNNN``
  and what was relaunched (see ``installer.classify_result``). The
  previous attempt's MSI log is moved to ``msi-install.prev.log`` right
  before the installer runs again.
- **Nothing is looked up by name** (helper v3).  cmd.exe searches the
  current directory — the staging directory, writable by every local
  account — before ``PATH``, so every tool runs by its System32 path, and
  ``cmd.exe`` itself is started by absolute path with AutoRun off (``/d``).
  Delayed expansion is forced off: a registry ``DelayedExpansion=1``
  would strip any ``!`` from a path.
- **It clears the update-in-progress marker** (``install_marker``) on
  every exit path, right before the relaunch: while it names this helper,
  a Mixar opened by hand quits instead of purging this very script.
- **The re-check pins the signer.**  Just before installing, the MSI must
  still be validly signed by the certificate whose thumbprint the app
  verified (``%SIGNER%``), not merely by anyone.

Paths reach PowerShell through environment variables set by the script
rather than through its command line. Start-Process still joins its
ArgumentList into one command line, so each path needs explicit quotes.
"""

import ntpath
import os
import string
import subprocess

from mixar.config.logging_config import get_logger

from ..constants import (
    HELPER_LOG_NAME,
    HELPER_MARKER_NAME,
    HELPER_REOPEN_GRACE_S,
    HELPER_REOPEN_NAME,
    HELPER_REOPEN_WAIT_S,
    HELPER_VERSION,
    HELPER_WAIT_FOR_EXIT_S,
    HELPER_WAIT_FOR_LOCKS_S,
    MSI_LOG_NAME,
    MSI_PREV_LOG_NAME,
    TRIGGER_CLICK,
    TRIGGERS,
)
from .app_paths import windows_system_dir
from .staging import result_path
# The PowerShell steps; re-exported because the tests read them from here.
from .win_helper_ps import (  # noqa: F401
    _PS_END_CONNECTORS,
    _PS_FINISH,
    _PS_INSTALL,
    _PS_LOCKS,
    _PS_VERIFY,
)

logger = get_logger(__name__)

# CREATE_NO_WINDOW, not DETACHED_PROCESS: detached gives cmd.exe no console
# at all, so every console child the wait loop spawns each second (tasklist,
# find, ping, powershell) allocates its own brand-new VISIBLE window — the
# user watches terminals flash for the whole wait. A hidden console is
# inherited by all of them and nothing ever shows.
_CREATE_NO_WINDOW = 0x08000000
_CREATE_NEW_PROCESS_GROUP = 0x00000200
# If Mixar itself runs inside a kill-on-close job object (some launchers and
# IDEs do this), a child in the same job dies the moment Mixar quits — which
# is exactly when the helper's work starts. Breakaway is attempted first and
# dropped if the job forbids it.
_CREATE_BREAKAWAY_FROM_JOB = 0x01000000

# Characters that would break out of batch quoting. Paths are ours or come
# from environment variables, so this is a guard rather than a limitation:
# if one ever trips we fall back to the browser download instead of writing
# a script that does something unintended.
_UNSAFE_BATCH_CHARS = ('"', "%", "^", "&", "|", "<", ">", "\r", "\n")

_POWERSHELL = '"%PWSH%" -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command'

_SCRIPT_TEMPLATE = '''@echo off
title Mixar Update
setlocal enableextensions disabledelayedexpansion
rem Every tool runs by its System32 path: a bare name is looked up in the
rem current directory first, and that is the shared staging directory.
set "SYS32={system_dir}"
set "PWSH=%SYS32%\\WindowsPowerShell\\v1.0\\powershell.exe"
set "LOG={log}"
set "MSI={msi}"
set "MSILOG={msi_log}"
set "MSIPREVLOG={msi_prev_log}"
set "RESULT={result}"
set "LOCKS={locks}"
set "MARKER={marker}"
set "REOPEN={reopen}"
set "REOPENWAIT={reopen_wait_s}"
set "REOPENGRACE={reopen_grace_s}"
set "RELAUNCHMODE={relaunch_mode}"
set "TRIGGER={trigger}"
set "PID={pid}"
set "VERSION={version}"
set "FROM_VERSION={from_version}"
set "ATTEMPT={attempt_id}"
set "INSTALLDIR={install_dir}"
set "RELAUNCH={relaunch_env}"
set "INSTALL_EXIT=1"
set "STAGE="

echo [%DATE% %TIME%] Mixar update helper started for %VERSION% (from %FROM_VERSION%, attempt %ATTEMPT%, trigger %TRIGGER%) >>"%LOG%" 2>&1

rem ---- wait for the running Mixar to exit -------------------------------
rem CSV output is matched on the quoted PID field, so a PID that also occurs
rem inside the memory column cannot read as "still running". Both sides of
rem the pipe stay unquoted: cmd re-parses each in a child shell, and a
rem broken parse would read as "exited" and install over the running app.
rem SYS32 never needs quotes (app_paths.windows_system_dir).
set /a WAITED=0
:waitloop
%SYS32%\\tasklist.exe /NH /FO CSV /FI "PID eq %PID%" 2>nul | %SYS32%\\find.exe """%PID%""" >nul
if errorlevel 1 goto gone
if %WAITED% GEQ {wait_s} goto timeout
"%SYS32%\\ping.exe" -n 2 127.0.0.1 >nul
set /a WAITED+=1
goto waitloop

:timeout
echo [%DATE% %TIME%] Mixar (pid %PID%) still running after {wait_s}s - aborting >>"%LOG%" 2>&1
call :result wait timeout
del /f /q "%MARKER%" >nul 2>&1
del /f /q "%REOPEN%" >nul 2>&1
exit /b 2

:gone
rem let Windows release the file handles the installer needs
"%SYS32%\\ping.exe" -n 3 127.0.0.1 >nul
set /a WAITED+=2

rem ---- end Mixar connectors respawned since the app's own check ---------
rem An AI app restarts its MCP server (our python.exe) on its next tool
rem call; one started after Restart & Update checked would keep the python
rem runtime in use and turn the install into a reboot. Connectors hold no
rem user work and are stale once Mixar restarts, so they are ended here as
rem the app did before quitting. A python started by a Mixar is left alone.
if not "%INSTALLDIR%"=="" {powershell} "{ps_end_connectors}" >>"%LOG%" 2>&1

rem ---- wait for everything else running from the install directory -----
rem Other Mixar windows and the asset-preview worker run binaries from
rem there. Windows Installer cannot replace a file in use: it defers it to
rem the next reboot, reports 3010, and the relaunch starts the old build.
rem They are waited for, never closed - the user may have unsaved work.
set /a LOCKWAIT=0
:lockloop
if "%INSTALLDIR%"=="" goto unlocked
{powershell} "{ps_locks}" >>"%LOG%" 2>&1
if not "%ERRORLEVEL%"=="3" goto unlocked
if %LOCKWAIT% GEQ {lock_wait_s} goto locked
"%SYS32%\\ping.exe" -n 3 127.0.0.1 >nul
set /a LOCKWAIT+=3
set /a WAITED+=3
goto lockloop

:locked
echo [%DATE% %TIME%] Files in %INSTALLDIR% still in use after {lock_wait_s}s - not installing >>"%LOG%" 2>&1
call :result locked locked
type "%LOCKS%" >>"%RESULT%" 2>nul
del /f /q "%LOCKS%" >nul 2>&1
goto finish

:unlocked
del /f /q "%LOCKS%" >nul 2>&1
echo [%DATE% %TIME%] Mixar exited - installing %MSI% >>"%LOG%" 2>&1
{signature_check}
rem ---- install (raises the UAC prompt) ----------------------------------
rem The previous attempt's MSI log survives as the .prev log.
if exist "%MSILOG%" move /y "%MSILOG%" "%MSIPREVLOG%" >nul 2>&1
rem PowerShell's presence is checked directly: cmd's status for a program
rem missing by absolute path is not reliably 9009.
set "INSTALL_EXIT=9009"
if not exist "%PWSH%" goto nopowershell
{powershell} "{ps_install}" >>"%LOG%" 2>&1
set "INSTALL_EXIT=%ERRORLEVEL%"
if not "%INSTALL_EXIT%"=="9009" goto installed

:nopowershell
echo [%DATE% %TIME%] PowerShell unavailable - falling back to msiexec >>"%LOG%" 2>&1
"%SYS32%\\msiexec.exe" /i "%MSI%" /passive /norestart REBOOT=ReallySuppress LAUNCHAPP=0 /l*v "%MSILOG%" >>"%LOG%" 2>&1
set "INSTALL_EXIT=%ERRORLEVEL%"

:installed
echo [%DATE% %TIME%] Installer exit code: %INSTALL_EXIT% >>"%LOG%" 2>&1
call :result install %INSTALL_EXIT%
if "%INSTALL_EXIT%"=="0"    del /f /q "%MSI%" >nul 2>&1
if "%INSTALL_EXIT%"=="3010" del /f /q "%MSI%" >nul 2>&1

:finish
rem ---- record what was installed, then bring Mixar back -----------------
rem Every exit path but the timeout comes through here. The in-progress
rem marker goes first: the Mixar about to start must not find it naming us.
del /f /q "%MARKER%" >nul 2>&1
rem Runs whatever the installer decided. The registered InstallLocation is
rem tried first; the fixed candidates below only when PowerShell cannot run.
rem Installed on quit, Mixar stays closed (4) unless a launch was turned away.
{powershell} "{ps_finish}" >>"%LOG%" 2>&1
if "%ERRORLEVEL%"=="0" goto relaunched
if "%ERRORLEVEL%"=="4" goto stayclosed
if not "%RELAUNCHMODE%"=="1" if not exist "%REOPEN%" goto stayclosed
del /f /q "%REOPEN%" >nul 2>&1
{relaunch}
echo [%DATE% %TIME%] No Mixar executable found to relaunch >>"%LOG%" 2>&1
exit /b %INSTALL_EXIT%

:stayclosed
echo [%DATE% %TIME%] Installed on quit - Mixar stays closed >>"%LOG%" 2>&1
exit /b %INSTALL_EXIT%

:relaunched
echo [%DATE% %TIME%] Relaunched Mixar >>"%LOG%" 2>&1
exit /b %INSTALL_EXIT%

:result
rem usage: call :result STAGE EXIT - starts a fresh result file
set "STAGE=%~1"
>"%RESULT%" echo version=%VERSION%
>>"%RESULT%" echo stage=%~1
>>"%RESULT%" echo exit=%~2
>>"%RESULT%" echo from_version=%FROM_VERSION%
>>"%RESULT%" echo attempt_id=%ATTEMPT%
>>"%RESULT%" echo helper_version={helper_version}
>>"%RESULT%" echo trigger=%TRIGGER%
>>"%RESULT%" echo wait_s=%WAITED%
goto :eof
'''

_SIGNATURE_CHECK = '''
rem ---- re-check the signature immediately before running it -------------
rem ONLY exit 0 passes. Anything else fails closed: 1 is an invalid
rem signature or another signer than the certificate the app verified, and
rem 9009 (PowerShell missing) used to fall through to signature_ok,
rem skipping the re-verify entirely.
set "SIGNER={signer}"
{powershell} "{ps_verify}" >>"%LOG%" 2>&1
if "%ERRORLEVEL%"=="0" goto signature_ok
echo [%DATE% %TIME%] Installer signature could not be verified - refusing to install >>"%LOG%" 2>&1
call :result verify signature
del /f /q "%MSI%" >nul 2>&1
set "INSTALL_EXIT=1"
goto finish
:signature_ok
'''


def _is_batch_safe(*values) -> bool:
    return not any(
        char in str(value) for value in values for char in _UNSAFE_BATCH_CHARS
    )


def _relaunch_block(candidates) -> str:
    """Batch fallback that starts the first candidate that exists."""
    lines = []
    for path in candidates:
        lines.append(f'if exist "{path}" (')
        lines.append(f'    start "" "{path}"')
        lines.append('    >>"%RESULT%" echo relaunch_kind=fallback')
        lines.append("    goto relaunched")
        lines.append(")")
    return "\n".join(lines)


def _hex(value) -> str:
    """A certificate thumbprint reduced to hex digits (it is embedded in the script)."""
    return "".join(char for char in str(value or "") if char in string.hexdigits).upper()


def build_script(
    *,
    installer_path,
    staging_dir,
    version,
    pid,
    relaunch_candidates,
    require_signature,
    signer_thumbprint="",
    install_dir="",
    from_version="",
    attempt_id="",
    system_dir="",
    relaunch=True,
    trigger=TRIGGER_CLICK,
):
    """Return the helper batch script text (pure — exercised directly by tests).

    *relaunch* False is an install on quit: Mixar is reopened only for a
    launch that was turned away while the helper worked.
    """
    if trigger not in TRIGGERS:
        raise ValueError(f"Unknown update trigger: {trigger!r}")
    return _SCRIPT_TEMPLATE.format(
        system_dir=system_dir or windows_system_dir(),
        log=os.path.join(staging_dir, HELPER_LOG_NAME),
        msi=installer_path,
        msi_log=os.path.join(staging_dir, MSI_LOG_NAME),
        msi_prev_log=os.path.join(staging_dir, MSI_PREV_LOG_NAME),
        result=result_path(staging_dir),
        locks=os.path.join(staging_dir, "mixar-update-locks.txt"),
        marker=os.path.join(staging_dir, HELPER_MARKER_NAME),
        reopen=os.path.join(staging_dir, HELPER_REOPEN_NAME),
        reopen_wait_s=int(HELPER_REOPEN_WAIT_S),
        reopen_grace_s=int(HELPER_REOPEN_GRACE_S),
        relaunch_mode="1" if relaunch else "0",
        trigger=trigger,
        pid=int(pid),
        version=version,
        from_version=from_version,
        attempt_id=attempt_id,
        install_dir=install_dir,
        relaunch_env="|".join(relaunch_candidates),
        wait_s=int(HELPER_WAIT_FOR_EXIT_S),
        lock_wait_s=int(HELPER_WAIT_FOR_LOCKS_S),
        helper_version=int(HELPER_VERSION),
        powershell=_POWERSHELL,
        signature_check=(
            _SIGNATURE_CHECK.format(
                powershell=_POWERSHELL, ps_verify=_PS_VERIFY, signer=_hex(signer_thumbprint))
            if require_signature else ""
        ),
        ps_install=_PS_INSTALL,
        ps_end_connectors=_PS_END_CONNECTORS,
        ps_locks=_PS_LOCKS,
        ps_finish=_PS_FINISH,
        relaunch=_relaunch_block(relaunch_candidates),
    )


def launch(
    *,
    installer_path,
    staging_dir,
    version,
    relaunch_candidates,
    require_signature=False,
    signer_thumbprint="",
    install_dir="",
    from_version="",
    attempt_id="",
    relaunch=True,
    trigger=TRIGGER_CLICK,
):
    """Write the helper script and start it detached.

    Returns the helper's ``subprocess.Popen``.

    Raises:
        OSError: the script could not be written or started — the caller
            must not quit the app.
        ValueError: a path could not be safely embedded in a batch script.
    """
    candidates = [path for path in relaunch_candidates if path]
    system_dir = windows_system_dir()
    if not _is_batch_safe(
        installer_path, staging_dir, version, install_dir, from_version, attempt_id,
        system_dir, *candidates,
    ):
        raise ValueError("Update paths contain characters unsafe for a batch script")

    script_path = os.path.join(staging_dir, f"mixar-update-{version}.cmd")
    script = build_script(
        installer_path=installer_path,
        staging_dir=staging_dir,
        version=version,
        pid=os.getpid(),
        relaunch_candidates=candidates,
        require_signature=require_signature,
        signer_thumbprint=signer_thumbprint,
        install_dir=install_dir,
        from_version=from_version,
        attempt_id=attempt_id,
        system_dir=system_dir,
        relaunch=relaunch,
        trigger=trigger,
    )
    # cp1252 matches cmd.exe's default code page. The script is ASCII unless
    # a path is not, and strict encoding makes that fail here rather than
    # producing a mangled script that half-runs.
    with open(script_path, "w", encoding="cp1252", newline="\r\n") as handle:
        handle.write(script)

    popen_kwargs = dict(
        cwd=staging_dir,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    # Absolute, like every tool the script runs; /d skips any AutoRun
    # command (clink, a cd) the user's cmd.exe registry settings add.
    argv = [ntpath.join(system_dir, "cmd.exe"), "/d", "/c", script_path]
    flags = _CREATE_NO_WINDOW | _CREATE_NEW_PROCESS_GROUP
    try:
        proc = subprocess.Popen(  # noqa: S603 - fixed argv, our own script
            argv, creationflags=flags | _CREATE_BREAKAWAY_FROM_JOB, **popen_kwargs,
        )
    except OSError:
        # The job we run in forbids breakaway — spawn inside it and hope it
        # is not kill-on-close; refusing to update over this would be worse.
        proc = subprocess.Popen(  # noqa: S603 - fixed argv, our own script
            argv, creationflags=flags, **popen_kwargs,
        )
    logger.info("Windows update helper started: %s (pid %s)", script_path, proc.pid)
    return proc
