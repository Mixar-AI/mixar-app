REM SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
REM
REM SPDX-License-Identifier: GPL-2.0-or-later

@echo off
setlocal enabledelayedexpansion

REM Mixar Clean Build Script for Windows
REM Deletes environment-specific build directory and source directory, then runs a fresh build via build.bat.
REM
REM Usage:
REM   build_clean.bat          Interactive (prompts for confirmation)
REM   build_clean.bat --yes    Non-interactive (skips confirmation, for CI/release scripts)

REM Load settings to resolve BUILD_DIR, SOURCE_DIR, and MIXAR_ENV
set "SCRIPT_DIR=%~dp0"
call "%SCRIPT_DIR%settings.bat"
if %ERRORLEVEL% neq 0 (
    echo Error: Failed to load settings
    exit /b 1
)

REM MIXAR_ENV may be empty here if settings parse fails partially — use fallback
if "%MIXAR_ENV%"=="" set "MIXAR_ENV=Prod"

REM Environment-specific build directory (e.g., build\Prod, build\Dev)
set "BUILD_ENV_DIR=%BUILD_DIR%\%MIXAR_ENV%"

echo === Clean Build Starting ===
echo This will delete the following directories:
echo   - Build (%MIXAR_ENV%):  %BUILD_ENV_DIR%
echo   - Source: %SOURCE_DIR%
echo.

REM Check for --yes flag (non-interactive mode for CI/release scripts)
set "AUTO_CONFIRM="
if /I "%~1"=="--yes" set "AUTO_CONFIRM=1"
if /I "%~1"=="-y" set "AUTO_CONFIRM=1"
if defined AUTO_CONFIRM goto :confirmed

set /P CONFIRM=Are you sure you want to proceed? (y/N):
if /I not "%CONFIRM%"=="y" (
    echo Aborted.
    exit /b 1
)
:confirmed
echo.

if exist "%BUILD_ENV_DIR%" (
    echo Deleting build directory: %BUILD_ENV_DIR%
    rmdir /s /q "%BUILD_ENV_DIR%"
    echo Build directory deleted.
) else (
    echo Build directory does not exist, skipping.
)

if exist "%SOURCE_DIR%" (
    echo Deleting source directory: %SOURCE_DIR%
    rmdir /s /q "%SOURCE_DIR%"
    echo Source directory deleted.
) else (
    echo Source directory does not exist, skipping.
)

echo.
echo === Starting Fresh Build ===
call "%SCRIPT_DIR%build.bat"
exit /b %ERRORLEVEL%
