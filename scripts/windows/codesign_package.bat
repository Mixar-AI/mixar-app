REM SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
REM
REM SPDX-License-Identifier: GPL-2.0-or-later

@echo off
setlocal enabledelayedexpansion

REM Sign the final Mixar MSI after package.bat creates it.
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

set "INSTALLER_OUTPUT_DIR=%ROOT_DIR%\dist"

if "%PROCESSOR_ARCHITECTURE%"=="AMD64" (
    set "PACKAGE_ARCH=x64"
) else if "%PROCESSOR_ARCHITECTURE%"=="ARM64" (
    set "PACKAGE_ARCH=arm64"
) else (
    set "PACKAGE_ARCH=%PROCESSOR_ARCHITECTURE%"
)

if not defined PACKAGE_NAME_OVERRIDE (
    if "%MIXAR_ENV%"=="Prod" (
        set "PACKAGE_NAME_OVERRIDE=Mixar-%MIXAR_VERSION%-%PACKAGE_ARCH%"
    ) else (
        set "PACKAGE_NAME_OVERRIDE=Mixar-%MIXAR_VERSION%-%MIXAR_ENV%-%PACKAGE_ARCH%"
    )
)

set "MSI_PATH=%INSTALLER_OUTPUT_DIR%\%PACKAGE_NAME_OVERRIDE%.msi"

echo ============================================================
echo Mixar Code Signing - MSI Package
echo ============================================================
echo Environment : %MIXAR_ENV%
echo MSI         : %MSI_PATH%
echo.

if not exist "%MSI_PATH%" (
    echo Error: MSI not found: %MSI_PATH%
    echo        Run scripts\windows\package.bat %MIXAR_ENV% first.
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%codesign-tools\sign-package.ps1" -PackageRoot "%MSI_PATH%" %*
exit /b %ERRORLEVEL%

:usage
echo Usage: scripts\windows\codesign_package.bat [PowerShell signing options]
echo.
echo Signs the final MSI in dist after scripts\windows\package.bat creates it.
echo MIXAR_ENV defaults to Prod. Pass -Force to re-sign an already-valid MSI.
exit /b 0
