REM SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
REM
REM SPDX-License-Identifier: GPL-2.0-or-later

@echo off
setlocal enabledelayedexpansion

REM Mixar Install Script for Windows
REM Installs scripts using CMake

REM Load all settings from settings.bat
set "SCRIPT_DIR=%~dp0"
call "%SCRIPT_DIR%settings.bat"

REM Use MIXAR_ENV directly from settings.bat (loaded from mixar.json)
REM Define build directory for this environment
if "%MIXAR_ENV%"=="" (
    echo Warning: MIXAR_ENV is empty, using fallback Prod
    set "MIXAR_ENV=Prod"
)
set "BUILD_ENV_DIR=%BUILD_DIR%\%MIXAR_ENV%"
set "BLENDER_BUILD_ENV=Release"

echo Clearing previous source directory...
cd /d "%ROOT_DIR%"
if exist "%SOURCE_DIR%\scripts" rmdir /s /q "%SOURCE_DIR%\scripts"
mkdir "%SOURCE_DIR%\scripts"

robocopy "%UPSTREAM_DIR%\scripts" "%SOURCE_DIR%\scripts" /E /COPY:DAT
if !ERRORLEVEL! GEQ 8 (
    echo Error: Failed to copy upstream scripts
    exit /b 1
)

echo Overlaying Mixar scripts onto source...
robocopy "%SRC_DIR%\scripts" "%SOURCE_DIR%\scripts" /E /COPY:DAT
if !ERRORLEVEL! GEQ 8 (
    echo Error: Failed to overlay Mixar scripts
    exit /b 1
)

REM Reset ERRORLEVEL before cmake
cmd /c "exit /b 0"

echo Installing scripts using CMake...
if defined BUILD_WITH_NINJA (
    cmake --build "%BUILD_ENV_DIR%" --target install
) else (
    cmake --build "%BUILD_ENV_DIR%" --target install --config "%BLENDER_BUILD_ENV%"
)

if !ERRORLEVEL! neq 0 (
    echo Error: Scripts install failed
    exit /b 1
)

echo Scripts installation complete.
echo Run Mixar using: %BUILD_ENV_DIR%\bin\%BLENDER_BUILD_ENV%\mixar.exe
exit /b 0
