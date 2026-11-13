# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Windows Update Helper — Batch Script Text

The batch script the helper runs (:mod:`win_installer` fills it in and
starts it), next to its PowerShell steps in :mod:`win_helper_ps`. The text
is ASCII and names no path (helper v8): cmd.exe reads a batch file in the
console's OEM code page, so the paths, version and attempt id reach it as
environment variables (``win_installer.helper_environment``). ``{...}``
fields are numbers, enums, ``SYS32`` (validated) and PowerShell text.
"""

_SCRIPT_TEMPLATE = '''@echo off
title Mixar Update
setlocal enableextensions disabledelayedexpansion
rem Every tool runs by its System32 path: a bare name is looked up in the
rem current directory first, and that is the shared staging directory.
set "SYS32={system_dir}"
set "PWSH=%SYS32%\\WindowsPowerShell\\v1.0\\powershell.exe"
rem LOG, MSI, MSILOG, MSIPREVLOG, RESULT, LOCKS, MARKER, REOPEN, INSTALLDIR,
rem RELAUNCH, RELAUNCH1..9, ELEVNOTE, VERSION, FROM_VERSION and ATTEMPT come
rem from the environment (helper v8): cmd reads this file in the OEM code
rem page, so a path written here would lose every non-ASCII letter of the
rem profile name. They are only ever used quoted.
set "REOPENWAIT={reopen_wait_s}"
set "REOPENGRACE={reopen_grace_s}"
set "RELAUNCHMODE={relaunch_mode}"
set "TRIGGER={trigger}"
set "PID={pid}"
set "ELEVATE={elevate}"
set "ELEVATEFALLBACK={elevate_fallback}"
set "MSIPROPS={msi_properties}"
set "UPGRADECODE={upgrade_code}"
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
echo [%DATE% %TIME%] Files in the install directory still in use after {lock_wait_s}s - not installing >>"%LOG%" 2>&1
call :result locked locked
type "%LOCKS%" >>"%RESULT%" 2>nul
del /f /q "%LOCKS%" >nul 2>&1
goto finish

:heldverify
rem The install step holds the installer open, re-checks its signature and
rem only then runs msiexec; 77 means it could not be held or failed that.
echo [%DATE% %TIME%] Installer could not be held or failed its re-check - refusing to install >>"%LOG%" 2>&1
call :result verify signature
del /f /q "%MSI%" >nul 2>&1
set "INSTALL_EXIT=1"
goto finish

:unlocked
del /f /q "%LOCKS%" >nul 2>&1
echo [%DATE% %TIME%] Mixar exited - installing %VERSION% >>"%LOG%" 2>&1
{signature_check}
rem ---- install (UAC prompt only when ELEVATE is 1) -----------------------
rem The previous attempt's MSI log survives as the .prev log.
if exist "%MSILOG%" move /y "%MSILOG%" "%MSIPREVLOG%" >nul 2>&1
del /f /q "%ELEVNOTE%" >nul 2>&1
rem PowerShell's presence is checked directly: cmd's status for a program
rem missing by absolute path is not reliably 9009.
set "INSTALL_EXIT=9009"
if not exist "%PWSH%" goto nopowershell
{powershell} "{ps_install}" >>"%LOG%" 2>&1
set "INSTALL_EXIT=%ERRORLEVEL%"
if "%INSTALL_EXIT%"=="77" goto heldverify
if not "%INSTALL_EXIT%"=="9009" goto installed

:nopowershell
echo [%DATE% %TIME%] PowerShell unavailable - falling back to msiexec >>"%LOG%" 2>&1
"%SYS32%\\msiexec.exe" /i "%MSI%" /passive /norestart REBOOT=ReallySuppress LAUNCHAPP=0 %MSIPROPS% /l*v "%MSILOG%" >>"%LOG%" 2>&1
set "INSTALL_EXIT=%ERRORLEVEL%"

:installed
echo [%DATE% %TIME%] Installer exit code: %INSTALL_EXIT% >>"%LOG%" 2>&1
call :result install %INSTALL_EXIT%
type "%ELEVNOTE%" >>"%RESULT%" 2>nul
del /f /q "%ELEVNOTE%" >nul 2>&1
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
