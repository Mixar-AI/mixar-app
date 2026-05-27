REM SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
REM
REM SPDX-License-Identifier: GPL-2.0-or-later

@echo off
setlocal enabledelayedexpansion

REM ==========================================================================
REM Mixar Windows Release Script
REM Runs a clean build, packages the MSI installer, and uploads to S3.
REM
REM Usage:
REM   release.bat [options]
REM
REM Options:
REM   --skip-upload          Skip S3 upload
REM   -h, --help             Show usage
REM
REM Environment variables:
REM   S3_BUCKET              S3 bucket name (required unless --skip-upload)
REM   S3_PREFIX              S3 base prefix (default: releases/), version is appended
REM ==========================================================================

set "SCRIPT_DIR=%~dp0"
set "SKIP_UPLOAD="

REM --- Parse Arguments ---
:parse_args
if "%~1"=="" goto :args_done
if /I "%~1"=="--skip-upload"  ( set "SKIP_UPLOAD=1" & shift & goto :parse_args )
if /I "%~1"=="-h"             ( goto :usage )
if /I "%~1"=="--help"         ( goto :usage )
echo Unknown option: %~1
goto :usage
:args_done

REM --- Load Settings ---
call "%SCRIPT_DIR%settings.bat"
if %ERRORLEVEL% neq 0 (
    echo Error: Failed to load settings
    exit /b 1
)

if "%MIXAR_ENV%"=="" set "MIXAR_ENV=Prod"

REM --- Determine architecture ---
if "%PROCESSOR_ARCHITECTURE%"=="AMD64" (
    set "PACKAGE_ARCH=x64"
) else if "%PROCESSOR_ARCHITECTURE%"=="ARM64" (
    set "PACKAGE_ARCH=arm64"
) else (
    set "PACKAGE_ARCH=%PROCESSOR_ARCHITECTURE%"
)

REM --- Build artifact filename ---
REM Must match package.bat naming convention:
REM   Prod  -> Mixar-{version}-{arch}.msi
REM   Other -> Mixar-{version}-{env}-{arch}.msi
if "%MIXAR_ENV%"=="Prod" (
    set "PACKAGE_NAME_OVERRIDE=Mixar-%MIXAR_VERSION%-%PACKAGE_ARCH%"
) else (
    set "PACKAGE_NAME_OVERRIDE=Mixar-%MIXAR_VERSION%-%MIXAR_ENV%-%PACKAGE_ARCH%"
)
set "MSI_NAME=%PACKAGE_NAME_OVERRIDE%.msi"
set "MSI_PATH=%ROOT_DIR%\dist\%MSI_NAME%"

if not defined S3_PREFIX set "S3_PREFIX=releases/"
set "S3_PREFIX=%S3_PREFIX%%MIXAR_VERSION%/"

echo ============================================================
echo   Mixar Release
echo ============================================================
echo   Version     : %MIXAR_VERSION%
echo   Environment : %MIXAR_ENV%
echo   Architecture: %PACKAGE_ARCH%
echo   Output      : %MSI_PATH%
if not defined SKIP_UPLOAD (
    echo   S3 dest     : s3://%S3_BUCKET%/%S3_PREFIX%%MSI_NAME%
)
echo ============================================================
echo.

REM --- [1/3] Clean Build ---
echo === [1/3] Clean Build ===
call "%SCRIPT_DIR%build_clean.bat" --yes
if !ERRORLEVEL! neq 0 (
    echo Error: Build failed
    exit /b 1
)
echo.

REM --- [2/3] Package ---
echo === [2/3] Packaging ===

REM PACKAGE_NAME_OVERRIDE is set above and will be inherited by package.bat
REM via call (same cmd session), ensuring consistent artifact naming.
call "%SCRIPT_DIR%package.bat"
if !ERRORLEVEL! neq 0 (
    echo Error: Packaging failed
    exit /b 1
)

if not exist "%MSI_PATH%" (
    echo Error: Expected MSI not found at: %MSI_PATH%
    echo Contents of dist\:
    dir "%ROOT_DIR%\dist\" 2>nul
    exit /b 1
)
echo.

REM --- [3/3] Upload to S3 ---
if defined SKIP_UPLOAD (
    echo === [3/3] Skipping S3 upload ^(--skip-upload^) ===
    goto :done
)

echo === [3/3] Uploading to S3 ===

if "%S3_BUCKET%"=="" (
    echo Error: S3 bucket not specified.
    echo   Set the S3_BUCKET environment variable.
    exit /b 1
)

where aws >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo Error: AWS CLI not found. Install it from https://aws.amazon.com/cli/
    exit /b 1
)

set "S3_DEST=s3://%S3_BUCKET%/%S3_PREFIX%%MSI_NAME%"
echo Uploading: %MSI_PATH%
echo       To: %S3_DEST%

aws s3 cp "%MSI_PATH%" "%S3_DEST%"
if !ERRORLEVEL! neq 0 (
    echo Error: S3 upload failed
    exit /b 1
)
echo Upload complete.

:done
echo.
echo ============================================================
echo   Release Complete
echo ============================================================
echo   MSI : %MSI_PATH%
if not defined SKIP_UPLOAD (
    if not "%S3_BUCKET%"=="" echo   S3  : %S3_DEST%
)
echo ============================================================
exit /b 0

:usage
echo Usage: release.bat [options]
echo.
echo Options:
echo   --skip-upload          Skip S3 upload
echo   -h, --help             Show this help
echo.
echo Environment variables:
echo   S3_BUCKET              S3 bucket name (required unless --skip-upload)
echo   S3_PREFIX              S3 key prefix (default: releases/{version}/)
exit /b 0
