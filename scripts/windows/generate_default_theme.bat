REM SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
REM
REM SPDX-License-Identifier: GPL-2.0-or-later

@echo off
setlocal enabledelayedexpansion

REM Mixar Generate Default Theme Script for Windows
REM Generates userdef_default_theme.c from user preferences

REM Load all settings from settings.bat
set "SCRIPT_DIR=%~dp0"
call "%SCRIPT_DIR%settings.bat"
if %ERRORLEVEL% neq 0 (
    echo Error: Failed to load settings
    exit /b 1
)

set "MIXAR_ENV=Dev"
set "BUILD_ENV_DIR=%BUILD_DIR%\%MIXAR_ENV%"

REM Find Python binary in the build output
set "PY_BASE=%BUILD_ENV_DIR%\bin"
set "PYTHON_BIN="
for %%P in (
    "%PY_BASE%\%BLENDER_VERSION%\python\bin\python.exe"
    "%PY_BASE%\%BLENDER_VERSION%\python\bin\python3.exe"
) do (
    if exist "%%~P" (
        set "PYTHON_BIN=%%~P"
        goto :found_python
    )
)

:found_python
if not defined PYTHON_BIN (
    echo Warning: Python binary not found under: %PY_BASE%\%BLENDER_VERSION%\python\bin
    exit /b 1
)

echo Found Python binary: %PYTHON_BIN%

REM Windows user preferences path
set "USERPREF_PATH=%APPDATA%\Mixar\Mixar\%BLENDER_VERSION%\config\mixar_userpref.blend"

if not exist "%USERPREF_PATH%" (
    echo Error: User preferences file not found at: %USERPREF_PATH%
    exit /b 1
)

REM Generate theme C file
pushd "%SOURCE_DIR%\tools\utils"
"%PYTHON_BIN%" blender_theme_as_c.py "%USERPREF_PATH%"
if %ERRORLEVEL% neq 0 (
    popd
    echo Error: Theme generation failed
    exit /b 1
)
popd

REM Copy generated file to src overlay
copy "%SOURCE_DIR%\release\datafiles\userdef\userdef_default_theme.c" "%SRC_DIR%\release\datafiles\userdef\userdef_default_theme.c"

echo === Theme Generated Complete ===
exit /b 0
