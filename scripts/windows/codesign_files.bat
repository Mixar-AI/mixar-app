REM SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
REM
REM SPDX-License-Identifier: GPL-2.0-or-later

@echo off
setlocal enabledelayedexpansion

REM Sign Mixar app binaries before MSI creation.
REM Optional extra PowerShell args, such as -Force, are passed through.

if /I "%~1"=="--help" goto :usage
if /I "%~1"=="-h" goto :usage
if "%~1"=="/?" goto :usage

set "SCRIPT_DIR=%~dp0"
call "%SCRIPT_DIR%settings.bat"
if %ERRORLEVEL% neq 0 (
    echo Error: Failed to load settings
    exit /b 1
)

if "%MIXAR_ENV%"=="" set "MIXAR_ENV=Prod"

set "BUILD_ENV_DIR=%BUILD_DIR%\%MIXAR_ENV%"
set "PACKAGE_ROOT=%BUILD_ENV_DIR%\bin"

echo ============================================================
echo Mixar Code Signing - App Files
echo ============================================================
echo Environment : %MIXAR_ENV%
echo Package root: %PACKAGE_ROOT%
echo.

if not exist "%PACKAGE_ROOT%" (
    echo Error: Package root not found: %PACKAGE_ROOT%
    echo        Run scripts\windows\build.bat first.
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%codesign-tools\sign-package.ps1" -PackageRoot "%PACKAGE_ROOT%" %*
exit /b %ERRORLEVEL%

:usage
echo Usage: scripts\windows\codesign_files.bat [PowerShell signing options]
echo.
echo Signs the app binaries in build\%%MIXAR_ENV%%\bin before MSI creation.
echo MIXAR_ENV defaults to Prod. Pass -Force to re-sign already-valid files.
exit /b 0
