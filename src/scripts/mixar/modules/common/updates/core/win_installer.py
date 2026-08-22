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
- **Elevation is explicit.**  ``Start-Process -Verb RunAs`` raises the UAC
  prompt and reports whether the user accepted, instead of letting
  ``msiexec`` fail with 1925 in the cases where it will not self-elevate.
  Plain ``msiexec`` remains the fallback when PowerShell is unavailable.
- **The app always comes back.**  Relaunch runs whatever the installer
  returned — a declined UAC prompt must leave the user with the version
  they already had, not with nothing.
- **The outcome is written down.**  ``update-result.txt`` is the only way
  the relaunched app can tell the user that an update it started did not
  finish.

Paths reach PowerShell through environment variables set by the script
rather than through its command line, so there is no second layer of
quoting to get wrong.
"""

import os
import subprocess

from mixar.config.logging_config import get_logger

from ..constants import HELPER_LOG_NAME, HELPER_WAIT_FOR_EXIT_S
from .staging import result_path

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

_PS_INSTALL = (
    "$a=@('/i',$env:MSI,'/qb!','/norestart','REBOOT=ReallySuppress',"
    "'LAUNCHAPP=0','/l*v',$env:MSILOG);"
    "$p=Start-Process -FilePath 'msiexec.exe' -ArgumentList $a "
    "-Verb RunAs -Wait -PassThru;"
    "exit $p.ExitCode"
)

_PS_VERIFY = (
    "if((Get-AuthenticodeSignature -LiteralPath $env:MSI).Status -ne 'Valid')"
    "{exit 1};exit 0"
)

_SCRIPT_TEMPLATE = '''@echo off
title Mixar Update
setlocal enableextensions
set "LOG={log}"
set "MSI={msi}"
set "MSILOG={msi_log}"
set "RESULT={result}"
set "PID={pid}"
set "VERSION={version}"

echo [%DATE% %TIME%] Mixar update helper started for %VERSION% >>"%LOG%" 2>&1

rem ---- wait for the running Mixar to exit -------------------------------
rem CSV output is matched on the quoted PID field, so a PID that also occurs
rem inside the memory column cannot read as "still running".
set /a WAITED=0
:waitloop
tasklist /NH /FO CSV /FI "PID eq %PID%" 2>nul | find """%PID%""" >nul
if errorlevel 1 goto gone
if %WAITED% GEQ {wait_s} goto timeout
ping -n 2 127.0.0.1 >nul
set /a WAITED+=1
goto waitloop

:timeout
echo [%DATE% %TIME%] Mixar (pid %PID%) still running after {wait_s}s - aborting >>"%LOG%" 2>&1
>"%RESULT%" echo version=%VERSION%
>>"%RESULT%" echo stage=wait
>>"%RESULT%" echo exit=timeout
exit /b 2

:gone
rem let Windows release the file handles the installer needs
ping -n 3 127.0.0.1 >nul
echo [%DATE% %TIME%] Mixar exited - installing %MSI% >>"%LOG%" 2>&1
{signature_check}
rem ---- install (raises the UAC prompt) ----------------------------------
powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "{ps_install}" >>"%LOG%" 2>&1
set "INSTALL_EXIT=%ERRORLEVEL%"
if not "%INSTALL_EXIT%"=="9009" goto installed

echo [%DATE% %TIME%] PowerShell unavailable - falling back to msiexec >>"%LOG%" 2>&1
msiexec /i "%MSI%" /qb! /norestart REBOOT=ReallySuppress LAUNCHAPP=0 /l*v "%MSILOG%" >>"%LOG%" 2>&1
set "INSTALL_EXIT=%ERRORLEVEL%"

:installed
echo [%DATE% %TIME%] Installer exit code: %INSTALL_EXIT% >>"%LOG%" 2>&1
>"%RESULT%" echo version=%VERSION%
>>"%RESULT%" echo stage=install
>>"%RESULT%" echo exit=%INSTALL_EXIT%
if "%INSTALL_EXIT%"=="0"    del /f /q "%MSI%" >nul 2>&1
if "%INSTALL_EXIT%"=="3010" del /f /q "%MSI%" >nul 2>&1

rem ---- bring Mixar back, whatever the installer decided ------------------
{relaunch}
echo [%DATE% %TIME%] No Mixar executable found to relaunch >>"%LOG%" 2>&1
exit /b %INSTALL_EXIT%

:relaunched
echo [%DATE% %TIME%] Relaunched Mixar >>"%LOG%" 2>&1
exit /b %INSTALL_EXIT%
'''

_SIGNATURE_CHECK = '''
rem ---- re-check the signature immediately before running it -------------
powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "{ps_verify}" >>"%LOG%" 2>&1
if not "%ERRORLEVEL%"=="1" goto signature_ok
echo [%DATE% %TIME%] Installer signature invalid - refusing to install >>"%LOG%" 2>&1
>"%RESULT%" echo version=%VERSION%
>>"%RESULT%" echo stage=verify
>>"%RESULT%" echo exit=signature
del /f /q "%MSI%" >nul 2>&1
set "INSTALL_EXIT=1"
goto relaunchonly
:signature_ok
'''

_RELAUNCH_ONLY = '''
:relaunchonly
{relaunch}
exit /b %INSTALL_EXIT%
'''


def _is_batch_safe(*values) -> bool:
    return not any(
        char in str(value) for value in values for char in _UNSAFE_BATCH_CHARS
    )


def _relaunch_block(candidates) -> str:
    """Batch that starts the first candidate that exists, then jumps away."""
    lines = []
    for path in candidates:
        lines.append(f'if exist "{path}" (')
        lines.append(f'    start "" "{path}"')
        lines.append("    goto relaunched")
        lines.append(")")
    return "\n".join(lines)


def build_script(
    *,
    installer_path,
    staging_dir,
    version,
    pid,
    relaunch_candidates,
    require_signature,
):
    """Return the helper batch script text (pure — exercised directly by tests)."""
    relaunch = _relaunch_block(relaunch_candidates)
    script = _SCRIPT_TEMPLATE.format(
        log=os.path.join(staging_dir, HELPER_LOG_NAME),
        msi=installer_path,
        msi_log=os.path.join(staging_dir, "msi-install.log"),
        result=result_path(staging_dir),
        pid=int(pid),
        version=version,
        wait_s=int(HELPER_WAIT_FOR_EXIT_S),
        signature_check=(
            _SIGNATURE_CHECK.format(ps_verify=_PS_VERIFY) if require_signature else ""
        ),
        ps_install=_PS_INSTALL,
        relaunch=relaunch,
    )
    if require_signature:
        script += _RELAUNCH_ONLY.format(relaunch=relaunch)
    return script


def launch(
    *,
    installer_path,
    staging_dir,
    version,
    relaunch_candidates,
    require_signature=False,
):
    """Write the helper script and start it detached.

    Returns the helper script path.

    Raises:
        OSError: the script could not be written or started — the caller
            must not quit the app.
        ValueError: a path could not be safely embedded in a batch script.
    """
    candidates = [path for path in relaunch_candidates if path]
    if not _is_batch_safe(installer_path, staging_dir, version, *candidates):
        raise ValueError("Update paths contain characters unsafe for a batch script")

    script_path = os.path.join(staging_dir, f"mixar-update-{version}.cmd")
    script = build_script(
        installer_path=installer_path,
        staging_dir=staging_dir,
        version=version,
        pid=os.getpid(),
        relaunch_candidates=candidates,
        require_signature=require_signature,
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
    argv = ["cmd.exe", "/c", script_path]
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
