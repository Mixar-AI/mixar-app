REM SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
REM
REM SPDX-License-Identifier: GPL-2.0-or-later

@echo off
REM Mixar Application Settings for Windows
REM Source this file in batch scripts that need these settings
REM
REM Configuration priority:
REM   1. Environment variables (already set, e.g. from CI)
REM   2. .env file in repo root (local dev overrides)
REM   3. Hardcoded defaults below

REM Get the root directory relative to this settings.bat script
for %%i in ("%~dp0..\..") do set "ROOT_DIR=%%~fi"

REM Load .env if it exists (local dev overrides)
if exist "%ROOT_DIR%\.env" (
    for /f "usebackq eol=# tokens=1,* delims==" %%a in ("%ROOT_DIR%\.env") do (
        if not "%%a"=="" if not "%%b"=="" (
            REM Only set if not already defined (env vars take priority)
            if not defined %%a set "%%a=%%b"
        )
    )
)

REM Version always comes from VERSION file (canonical source)
if not defined MIXAR_VERSION (
    if exist "%ROOT_DIR%\VERSION" (
        set /p MIXAR_VERSION=<"%ROOT_DIR%\VERSION"
    ) else (
        set "MIXAR_VERSION=0.0.0"
    )
)

REM Core environment settings (env var > .env > default)
if not defined MIXAR_ENV set "MIXAR_ENV=Prod"
if not defined MIXAR_BACKEND_URL set "MIXAR_BACKEND_URL=https://api.mixar.app"
if not defined MIXAR_FRONTEND_URL set "MIXAR_FRONTEND_URL=https://www.mixar.app"

REM App info (constants)
if not defined MIXAR_VERSION_PATCH set "MIXAR_VERSION_PATCH=0"
if not defined MIXAR_APP_NAME set "MIXAR_APP_NAME=Mixar"
if not defined MIXAR_EXECUTABLE_NAME set "MIXAR_EXECUTABLE_NAME=mixar"
if not defined MIXAR_DESCRIPTION set "MIXAR_DESCRIPTION=AI Native 3D Content Creation Software"
if not defined MIXAR_VENDOR set "MIXAR_VENDOR=Mixar"
if not defined MIXAR_WEBSITE set "MIXAR_WEBSITE=https://mixar.app"

REM Bundle settings (constants)
if not defined MIXAR_BUNDLE_IDENTIFIER set "MIXAR_BUNDLE_IDENTIFIER=com.mixar.mixar"
if not defined MIXAR_BUNDLE_COPYRIGHT set "MIXAR_BUNDLE_COPYRIGHT=© 2025 Mixar"

REM Build settings (constants)
if not defined BLENDER_VERSION set "BLENDER_VERSION=5.0"
if not defined PYTHON_VERSION set "PYTHON_VERSION=3.11"
if not defined REQUIRED_CMAKE_VERSION set "REQUIRED_CMAKE_VERSION=3.16"

REM Windows-specific build settings
set "BLENDER_BUILD_TYPE=Release"

REM Directory Structure
set "BUILD_DIR=%ROOT_DIR%\build"
set "SOURCE_DIR=%ROOT_DIR%\source"
set "SRC_DIR=%ROOT_DIR%\src"
set "CMAKE_DIR=%ROOT_DIR%\cmake"
set "UPSTREAM_DIR=%ROOT_DIR%\upstream"

REM Platform-specific settings
set "PLATFORM=Windows"

REM Get number of CPU cores (Windows) - Reserve 2 cores for system
set /a "DEFAULT_CORES=%NUMBER_OF_PROCESSORS%-2"
if %DEFAULT_CORES% LEQ 2 set "DEFAULT_CORES=2"

REM Build optimization - Use BUILD_CORES if set, otherwise use DEFAULT_CORES
if not defined BUILD_CORES (
    set "BUILD_CORES=%DEFAULT_CORES%"
) else (
    echo Using custom BUILD_CORES: %BUILD_CORES%
)

REM Windows-specific build settings - Select generator based on BUILD_WITH_NINJA
if defined BUILD_WITH_NINJA (
    set "CMAKE_GENERATOR_ARGS=-G Ninja"
    set "BUILD_ARGS=--parallel %BUILD_CORES%"
) else (
    REM Use Visual Studio generator - multi-config, creates Debug/Release folders
    set "CMAKE_GENERATOR_ARGS=-G "Visual Studio 17 2022" -A x64"
    set "BUILD_ARGS=--parallel %BUILD_CORES% --verbose -- /m:%BUILD_CORES%"
)

exit /b 0
