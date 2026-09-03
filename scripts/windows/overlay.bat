REM SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
REM
REM SPDX-License-Identifier: GPL-2.0-or-later

@echo off
setlocal enabledelayedexpansion

REM Load all settings from settings.bat
set "SCRIPT_DIR=%~dp0"
call "%SCRIPT_DIR%\settings.bat"
if %errorlevel% neq 0 (
    echo Failed to load settings
    exit /b 1
)

REM Incremental overlay: only copy files newer than destination (preserves timestamps for
REM unchanged files so Ninja skips them). build_clean.bat handles full wipes when needed.
if not exist "%SOURCE_DIR%" mkdir "%SOURCE_DIR%"

REM Multi-threaded robocopy: set ROBOCOPY_THREADS env var to control thread count.
REM Default: 8 threads. CI can set higher (e.g. 32) for faster copies on large instances.
if not defined ROBOCOPY_THREADS set "ROBOCOPY_THREADS=8"

echo Copying upstream to source (threads: %ROBOCOPY_THREADS%)...
REM /E   = copy subdirectories including empty ones
REM /XO  = eXclude Older: skip destination files that are the same age or newer than source
REM /XD  = exclude directories  /XF = exclude files
REM /MT  = multi-threaded copy
REM /NFL /NDL /NJH /NJS /nc /ns /np = minimal output  /R:3 /W:1 = retry settings
robocopy "%UPSTREAM_DIR%" "%SOURCE_DIR%" /E /XO /MT:%ROBOCOPY_THREADS% ^
    /XD ".git" ".github" ".vscode" ".idea" ".gitea" ^
    /XF ".gitignore" ".gitmodules" ".gitattributes" ".gitkeep" ^
    /R:3 /W:1 /NFL /NDL /NJH /NJS /nc /ns /np

REM robocopy returns 0-7 for success, 8+ for errors
if %errorlevel% geq 8 (
    echo Error copying upstream to source
    exit /b 1
)

echo Overlaying Mixar sources onto source...
REM NO /XO here: Mixar src files must ALWAYS win over upstream, regardless of timestamps.
REM After a git pull, upstream files get newer timestamps than src/ files,
REM so /XO would wrongly skip the Mixar overlay, leaving the raw upstream version.
REM Without /XO, robocopy copies src files when timestamps differ (first run after pull),
REM then skips on subsequent runs when timestamps stabilize (Ninja sees no change).
REM Skip local-only artefacts git ignores inside src/ (stray venvs, .pyc caches);
REM CMake's scripts/ install rule only filters __pycache__, the rest would ship.
robocopy "%SRC_DIR%" "%SOURCE_DIR%" /E /MT:%ROBOCOPY_THREADS% /R:3 /W:1 /NFL /NDL /NJH /NJS /nc /ns /np ^
    /XD ".venv" "venv" "__pycache__" ".pytest_cache" ^
    /XF ".DS_Store"
REM robocopy returns 0-7 for success
if %errorlevel% geq 8 (
    echo Error overlaying Mixar sources
    exit /b 1
)

echo Overlay complete.
exit /b 0
