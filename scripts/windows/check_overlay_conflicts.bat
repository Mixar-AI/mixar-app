REM SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
REM
REM SPDX-License-Identifier: GPL-2.0-or-later

@echo off
setlocal enabledelayedexpansion

REM Upstream Overlay Conflict Detector for Windows
REM Detects when upstream Blender changes files that Mixar also overlays.
REM
REM Usage:
REM   check_overlay_conflicts.bat --generate   Generate/update the manifest
REM   check_overlay_conflicts.bat --check      Check for upstream changes (default)

set "SCRIPT_DIR=%~dp0"
call "%SCRIPT_DIR%settings.bat"
if %ERRORLEVEL% neq 0 (
    echo Error: Failed to load settings
    exit /b 1
)

set "MANIFEST_FILE=%ROOT_DIR%\.overlay_manifest"

if "%~1"=="--generate" goto :generate_manifest
if "%~1"=="--check" goto :check_conflicts
if "%~1"=="-h" goto :show_help
if "%~1"=="--help" goto :show_help
if "%~1"=="" goto :check_conflicts
echo Unknown option: %~1
goto :show_help

:show_help
echo Usage: %~nx0 [--generate^|--check]
echo.
echo   --generate  Record current upstream checksums for all overlaid files
echo   --check     Compare upstream against manifest to detect changes (default)
exit /b 0

:generate_manifest
echo Generating overlay conflict manifest...

set "TOTAL=0"
set "TRACKED=0"

REM Clear manifest
type nul > "%MANIFEST_FILE%"

REM Find all overlay files in src/ that correspond to upstream files
for /r "%SRC_DIR%" %%F in (*) do (
    set "FILE_PATH=%%F"
    REM Skip __pycache__ and .git directories
    echo !FILE_PATH! | findstr /i "__pycache__ .git" >nul 2>&1
    if !ERRORLEVEL! neq 0 (
        set /a "TOTAL+=1"
        REM Get relative path from SRC_DIR
        set "REL_PATH=!FILE_PATH:%SRC_DIR%\=!"
        set "UPSTREAM_FILE=%UPSTREAM_DIR%\!REL_PATH!"

        if exist "!UPSTREAM_FILE!" (
            REM Compute SHA-256 using certutil
            for /f "skip=1 tokens=*" %%H in ('certutil -hashfile "!UPSTREAM_FILE!" SHA256 2^>nul') do (
                set "HASH=%%H"
                goto :got_hash
            )
            :got_hash
            REM Skip the final "CertUtil" line
            echo !HASH! | findstr /i "certutil" >nul 2>&1
            if !ERRORLEVEL! neq 0 (
                echo !HASH!  !REL_PATH!>> "%MANIFEST_FILE%"
                set /a "TRACKED+=1"
            )
        )
    )
)

echo Manifest written: !TRACKED! overlaid upstream files tracked (out of !TOTAL! overlay files)
echo Location: %MANIFEST_FILE%
exit /b 0

:check_conflicts
if not exist "%MANIFEST_FILE%" (
    echo No overlay manifest found. Run with --generate to create one.
    exit /b 0
)

set "CONFLICTS=0"
set "REMOVED=0"
set "CHECKED=0"

for /f "tokens=1,* delims= " %%A in ('type "%MANIFEST_FILE%"') do (
    set "OLD_CHECKSUM=%%A"
    set "REL_PATH=%%B"
    set /a "CHECKED+=1"

    set "UPSTREAM_FILE=%UPSTREAM_DIR%\!REL_PATH!"

    if exist "!UPSTREAM_FILE!" (
        REM Compute current checksum
        for /f "skip=1 tokens=*" %%H in ('certutil -hashfile "!UPSTREAM_FILE!" SHA256 2^>nul') do (
            set "NEW_CHECKSUM=%%H"
            goto :got_check_hash
        )
        :got_check_hash
        echo !NEW_CHECKSUM! | findstr /i "certutil" >nul 2>&1
        if !ERRORLEVEL! neq 0 (
            if "!OLD_CHECKSUM!" neq "!NEW_CHECKSUM!" (
                echo   CONFLICT: !REL_PATH!
                set /a "CONFLICTS+=1"
            )
        )
    ) else (
        echo   REMOVED:  !REL_PATH! (no longer in upstream^)
        set /a "REMOVED+=1"
    )
)

echo Checked !CHECKED! files.

if !CONFLICTS! gtr 0 (
    echo.
    echo WARNING: !CONFLICTS! file(s) changed in upstream since last manifest.
)
if !REMOVED! gtr 0 (
    echo WARNING: !REMOVED! file(s) removed from upstream since last manifest.
)

if !CONFLICTS! gtr 0 (
    echo Review these files and update overlays as needed.
    echo Then run: %~nx0 --generate
    exit /b 1
)
if !REMOVED! gtr 0 (
    echo Review these files and update overlays as needed.
    echo Then run: %~nx0 --generate
    exit /b 1
)

echo No upstream conflicts detected.
exit /b 0
