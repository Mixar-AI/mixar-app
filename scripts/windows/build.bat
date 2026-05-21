REM SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
REM
REM SPDX-License-Identifier: GPL-2.0-or-later

@echo off
setlocal enabledelayedexpansion

REM Mixar Build Script for Windows
REM All build logic lives here. build_ninja.bat / build_ms.bat are thin wrappers.
REM BUILD_WITH_NINJA can be pre-set by callers; otherwise auto-detected here.

echo ============================================================
echo Mixar Build Script
echo ============================================================

REM --- [1/8] Generator Selection ---
REM build_ninja.bat sets BUILD_WITH_NINJA=1  (force Ninja)
REM build_ms.bat    sets BUILD_WITH_NINJA=0  (force MSBuild; normalize to unset so all downstream
REM                                           "if defined BUILD_WITH_NINJA" checks work correctly)
REM Not set at all  -> auto-detect (prefer Ninja: system PATH, then VS-bundled)
if "%BUILD_WITH_NINJA%"=="0" (
    set "BUILD_WITH_NINJA="
    echo [1/8] Using Visual Studio MSBuild ^(pre-selected^)...
) else if defined BUILD_WITH_NINJA (
    echo [1/8] Using Ninja build system ^(pre-selected^)...
) else (
    where ninja >nul 2>&1
    if !ERRORLEVEL! equ 0 (
        set "BUILD_WITH_NINJA=1"
        echo [1/8] Ninja detected on PATH, using Ninja build system...
    ) else (
        for %%E in (Community Professional Enterprise BuildTools) do (
            if exist "%ProgramFiles%\Microsoft Visual Studio\2022\%%E\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja\ninja.exe" (
                if not defined BUILD_WITH_NINJA set "BUILD_WITH_NINJA=1"
            )
        )
        if defined BUILD_WITH_NINJA (
            echo [1/8] VS-bundled Ninja detected, using Ninja build system...
        ) else (
            echo [1/8] Ninja not found, using Visual Studio ^(MSBuild^) build system...
        )
    )
)

REM --- Settings ---
set "SCRIPT_DIR=%~dp0"
REM Read .env with delayed expansion disabled so values containing ! survive.
setlocal DisableDelayedExpansion
call "%SCRIPT_DIR%settings.bat"
if %ERRORLEVEL% neq 0 (
    echo Error: Failed to load settings
    exit /b 1
)
setlocal EnableDelayedExpansion

set "BLENDER_BUILD_ENV=Release"

if "%MIXAR_ENV%"=="" (
    echo Warning: MIXAR_ENV is empty, defaulting to Prod
    set "MIXAR_ENV=Prod"
)
set "BUILD_ENV_DIR=%BUILD_DIR%\%MIXAR_ENV%"

if defined BUILD_WITH_NINJA (
    echo Generator  : Ninja ^(parallel: %BUILD_CORES% cores^)
) else (
    echo Generator  : Visual Studio MSBuild ^(parallel: %BUILD_CORES% cores^)
)
echo Build dir  : %BUILD_ENV_DIR%
echo Environment: %MIXAR_ENV%
echo.

REM --- [2/8] Build Start ---
echo [2/8] Starting build at %TIME%...

REM --- [3/8] Overlay ---
echo [3/8] Overlaying Mixar sources onto source...
call "%SCRIPT_DIR%overlay.bat"
if %ERRORLEVEL% neq 0 (
    echo Error: Overlay failed
    exit /b 1
)
echo [3/8] Overlay complete at %TIME%

REM Fix future timestamps (Ninja only).
REM Future-dated upstream files always appear newer than compiled objects, forcing full rebuilds.
REM Normalize them to a stable epoch (2000-01-01): cmake sees the same value every run,
REM and epoch is older than any real compiled object so Ninja skips unchanged files.
if defined BUILD_WITH_NINJA (
    echo Normalizing future-dated source timestamps to stable epoch...
    powershell -NoProfile -Command "$ep=[DateTime]::new(2000,1,1); Get-ChildItem -Path '%SOURCE_DIR%' -Recurse -File | Where-Object{$_.LastWriteTime -gt (Get-Date)} | ForEach-Object{$_.LastWriteTime=$ep}" 2>nul
)

REM --- [4/8] Header Generation ---
if not exist "%BUILD_ENV_DIR%" mkdir "%BUILD_ENV_DIR%"

echo [4/8] Generating environment config header for: %MIXAR_ENV%...
if not exist "%SOURCE_DIR%\source\creator" mkdir "%SOURCE_DIR%\source\creator"

set "HEADER_FILE=%SOURCE_DIR%\source\creator\mixar_env_config.h"
set "HEADER_TMP=%HEADER_FILE%.tmp"

REM Write to temp file first; only overwrite if content changed (preserves timestamp when unchanged,
REM preventing unnecessary recompilation of all files that include this header).
(
echo #pragma once
echo // Auto-generated file - DO NOT EDIT
echo // Generated for environment: %MIXAR_ENV%
echo.
echo #define MIXAR_BASE_URL "%MIXAR_BACKEND_URL%"
echo #define MIXAR_FRONTEND_BASE_URL "%MIXAR_FRONTEND_URL%"
echo #define MIXAR_CURRENT_ENV "%MIXAR_ENV%"
echo.
echo // Environment-specific macros for conditional compilation
) > "%HEADER_TMP%"

if "%MIXAR_ENV%"=="Prod" (
    echo #define MIXAR_ENV_PROD>> "%HEADER_TMP%"
) else if "%MIXAR_ENV%"=="Dev" (
    echo #define MIXAR_ENV_DEV>> "%HEADER_TMP%"
) else if "%MIXAR_ENV%"=="UAT" (
    echo #define MIXAR_ENV_UAT>> "%HEADER_TMP%"
) else if "%MIXAR_ENV%"=="Uat" (
    echo #define MIXAR_ENV_UAT>> "%HEADER_TMP%"
) else (
    echo #define MIXAR_ENV_PROD>> "%HEADER_TMP%"
)

fc /b "%HEADER_FILE%" "%HEADER_TMP%" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    copy /y "%HEADER_TMP%" "%HEADER_FILE%" >nul
    echo Header updated.
) else (
    echo Header unchanged, timestamp preserved.
)
del "%HEADER_TMP%"

REM Emit the build-frozen Python env marker (mirrors mixar_env_config.h
REM on the Python side). Gates mixar.config.config.get_dev_bypass_credentials
REM behind a value that cannot be flipped by editing the bundled mixar.json.
if "%MIXAR_ENV%"=="Dev" (
    set "BUILD_ENV_DEV_BYPASS=True"
) else (
    set "BUILD_ENV_DEV_BYPASS=False"
)
if not exist "%SOURCE_DIR%\scripts\mixar\config" mkdir "%SOURCE_DIR%\scripts\mixar\config"
(
    echo # SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
    echo # SPDX-License-Identifier: GPL-2.0-or-later
    echo # Auto-generated by scripts/windows/build.bat - DO NOT EDIT
    echo BUILD_ENVIRONMENT = "%MIXAR_ENV%"
    echo DEV_BYPASS_ALLOWED = %BUILD_ENV_DEV_BYPASS%
) > "%SOURCE_DIR%\scripts\mixar\config\_build_env.py"

REM --- Visual Studio Environment (Ninja only) ---
REM vcvarsall must be set up before cmake configure and before the build step.
if defined BUILD_WITH_NINJA (
    set "VCVARSALL="
    for %%E in (Community Professional Enterprise BuildTools) do (
        if exist "%ProgramFiles%\Microsoft Visual Studio\2022\%%E\VC\Auxiliary\Build\vcvarsall.bat" (
            set "VCVARSALL=%ProgramFiles%\Microsoft Visual Studio\2022\%%E\VC\Auxiliary\Build\vcvarsall.bat"
        )
        if exist "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\%%E\VC\Auxiliary\Build\vcvarsall.bat" (
            set "VCVARSALL=%ProgramFiles(x86)%\Microsoft Visual Studio\2022\%%E\VC\Auxiliary\Build\vcvarsall.bat"
        )
    )
    if not defined VCVARSALL (
        echo Error: Visual Studio 2022 not found. Install VS2022 with C++ workload.
        exit /b 1
    )
    echo Setting up Visual Studio toolchain for Ninja...
    call "!VCVARSALL!" x64
    if !ERRORLEVEL! neq 0 (
        echo Error: Failed to initialize Visual Studio environment
        exit /b 1
    )
)

REM --- CUDA Toolkit Detection ---
set "CUDA_FOUND="
if defined CUDA_PATH (
    if exist "%CUDA_PATH%\bin\nvcc.exe" (
        set "CUDA_FOUND=1"
        set "CUDA_TOOLKIT_ROOT=%CUDA_PATH%"
    )
)
if not defined CUDA_FOUND (
    for /d %%V in ("%ProgramFiles%\NVIDIA GPU Computing Toolkit\CUDA\v*") do (
        if exist "%%V\bin\nvcc.exe" (
            set "CUDA_FOUND=1"
            set "CUDA_TOOLKIT_ROOT=%%V"
        )
    )
)
if defined CUDA_FOUND (
    echo CUDA toolkit : !CUDA_TOOLKIT_ROOT!
    "!CUDA_TOOLKIT_ROOT!\bin\nvcc.exe" --version 2>nul | findstr /C:"release"
    REM Set CUDA_PATH so CMake's find_package(CUDA) auto-detects the toolkit.
    set "CUDA_PATH=!CUDA_TOOLKIT_ROOT!"
    set "CUDA_CMAKE_ARGS="
) else (
    echo Warning: CUDA toolkit not found. CUDA support will be disabled.
    echo   Install from: https://developer.nvidia.com/cuda-downloads
    set "CUDA_CMAKE_ARGS=-DWITH_CYCLES_DEVICE_CUDA=OFF"
)

REM --- OptiX SDK Detection ---
set "OPTIX_FOUND="
for /d %%D in ("%ProgramData%\NVIDIA Corporation\OptiX SDK*") do (
    if exist "%%D\include\optix.h" (
        set "OPTIX_FOUND=1"
        set "OPTIX_SDK_ROOT=%%D"
    )
)
if defined OPTIX_FOUND (
    echo OptiX SDK    : !OPTIX_SDK_ROOT!
    REM Set OPTIX_ROOT_DIR env var so CMake's FindOptiX auto-detects the SDK.
    set "OPTIX_ROOT_DIR=!OPTIX_SDK_ROOT!"
) else (
    echo Warning: OptiX SDK not found. OptiX support will be disabled.
    echo   Install from: https://developer.nvidia.com/optix/downloads
    set "CUDA_CMAKE_ARGS=!CUDA_CMAKE_ARGS! -DWITH_CYCLES_DEVICE_OPTIX=OFF"
)

REM --- CUDA Cache Invalidation ---
REM Force reconfigure when CUDA was enabled in overrides but the existing cache was built without it.
if defined CUDA_FOUND (
    if exist "%BUILD_ENV_DIR%\CMakeCache.txt" (
        findstr /C:"WITH_CYCLES_DEVICE_CUDA:BOOL=ON" "%BUILD_ENV_DIR%\CMakeCache.txt" >nul 2>&1
        if !ERRORLEVEL! neq 0 (
            echo Detected cache without CUDA support, forcing reconfigure...
            del /q "%BUILD_ENV_DIR%\CMakeCache.txt" 2>nul
            rmdir /s /q "%BUILD_ENV_DIR%\CMakeFiles" 2>nul
            if defined BUILD_WITH_NINJA del /q "%BUILD_ENV_DIR%\build.ninja" 2>nul
            echo CUDA cache invalidated.
        )
    )
)

REM --- Generator Switch Detection ---
REM Clean stale cmake cache when switching between Ninja and MSBuild.
REM IMPORTANT: match CMAKE_GENERATOR:INTERNAL= specifically.
REM "Visual Studio" appears in MSVC compiler paths in ANY cmake cache (even Ninja builds),
REM so a broad search for "Visual Studio" would always fire and wipe the Ninja cache.
if defined BUILD_WITH_NINJA (
    if exist "%BUILD_ENV_DIR%\CMakeCache.txt" (
        findstr /C:"CMAKE_GENERATOR:INTERNAL=Visual Studio" "%BUILD_ENV_DIR%\CMakeCache.txt" >nul 2>&1
        if !ERRORLEVEL! equ 0 (
            echo Detected stale Visual Studio cache, cleaning for Ninja...
            del /q "%BUILD_ENV_DIR%\CMakeCache.txt" 2>nul
            rmdir /s /q "%BUILD_ENV_DIR%\CMakeFiles" 2>nul
            del /q "%BUILD_ENV_DIR%\build.ninja" 2>nul
            echo Cache cleaned.
        )
    )
) else (
    if exist "%BUILD_ENV_DIR%\CMakeCache.txt" (
        findstr /C:"CMAKE_GENERATOR:INTERNAL=Ninja" "%BUILD_ENV_DIR%\CMakeCache.txt" >nul 2>&1
        if !ERRORLEVEL! equ 0 (
            echo Detected stale Ninja cache, cleaning for Visual Studio...
            del /q "%BUILD_ENV_DIR%\CMakeCache.txt" 2>nul
            rmdir /s /q "%BUILD_ENV_DIR%\CMakeFiles" 2>nul
            echo Cache cleaned.
        )
    )
)

REM --- [5/8] CMake Configure (once) ---
REM Following upstream pattern (upstream/build_files/windows/configure_ninja.cmd):
REM   if NOT EXIST build.ninja set MUST_CONFIGURE=1
REM Configure only when build files don't exist; subsequent runs skip straight to build.
echo [5/8] Checking CMake configuration...
set "MUST_CONFIGURE=0"
if defined BUILD_WITH_NINJA (
    if not exist "%BUILD_ENV_DIR%\build.ninja" set "MUST_CONFIGURE=1"
) else (
    if not exist "%BUILD_ENV_DIR%\Blender.sln" set "MUST_CONFIGURE=1"
)

if "%MUST_CONFIGURE%"=="1" (
    echo Configuring CMake...
    echo   Blender: %BLENDER_BUILD_ENV%   Mixar: %MIXAR_ENV%   Platform: %PLATFORM%

    cmake -C "%CMAKE_DIR%\mixar_overrides.cmake" ^
        %CMAKE_GENERATOR_ARGS% ^
        -S "%SOURCE_DIR%" ^
        -B "%BUILD_ENV_DIR%" ^
        -DCMAKE_BUILD_TYPE=%BLENDER_BUILD_ENV% ^
        -DWITH_WINDOWS_RELEASE_PDB=OFF ^
        -DCMAKE_EXPORT_COMPILE_COMMANDS=ON ^
        %CUDA_CMAKE_ARGS%

    if !ERRORLEVEL! neq 0 (
        echo Error: CMake configuration failed
        exit /b 1
    )
    echo [5/8] CMake configuration complete at %TIME%
) else (
    echo [5/8] CMake already configured — skipping ^(delete %BUILD_ENV_DIR% to reconfigure^)
)

REM --- [6/8] Build ---
echo [6/8] Building...
if defined BUILD_WITH_NINJA (
    cmake --build "%BUILD_ENV_DIR%" -- -j%BUILD_CORES%
) else (
    cmake --build "%BUILD_ENV_DIR%" --config "%BLENDER_BUILD_ENV%" --parallel %BUILD_CORES%
)
if %ERRORLEVEL% neq 0 (
    echo Error: Build failed
    exit /b 1
)

REM Install to BUILD_ENV_DIR\bin — same output location for both Ninja and MSBuild.
echo Installing build artifacts...
if defined BUILD_WITH_NINJA (
    cmake --install "%BUILD_ENV_DIR%" --prefix "%BUILD_ENV_DIR%\bin"
) else (
    cmake --install "%BUILD_ENV_DIR%" --prefix "%BUILD_ENV_DIR%\bin" --config "%BLENDER_BUILD_ENV%"
)
if %ERRORLEVEL% neq 0 (
    echo Error: Install failed
    exit /b 1
)
echo [6/8] Build complete at %TIME%

REM --- Find embedded Python (used by steps 7 and 8) ---
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
    echo Error: Python binary not found under: %PY_BASE%\%BLENDER_VERSION%\python\bin
    exit /b 1
)

echo Found Python: %PYTHON_BIN%

REM --- [7/8] Config File ---
echo [7/8] Generating runtime configuration for bundle...
set "BUNDLE_CONFIG_DIR=%BUILD_ENV_DIR%\bin\%BLENDER_VERSION%\config"
"!PYTHON_BIN!" "%ROOT_DIR%\scripts\generate_config.py" --output "%BUNDLE_CONFIG_DIR%\mixar.json"
if !ERRORLEVEL! neq 0 (
    echo Error: Failed to generate runtime configuration
    exit /b 1
)

REM --- [8/8] Python Packages ---
echo [8/8] Installing Python packages for Mixar...
set "SITE_PACKAGES=%PY_BASE%\%BLENDER_VERSION%\python\lib\site-packages"
set "REQUIREMENTS_FILE=%SCRIPT_DIR%..\python_requirements.txt"

REM Bootstrap pip if not available (Blender's embedded Python may lack it)
"!PYTHON_BIN!" -m pip --version >nul 2>&1
if !ERRORLEVEL! neq 0 (
    echo Bootstrapping pip with ensurepip...
    "!PYTHON_BIN!" -m ensurepip --upgrade
    if !ERRORLEVEL! neq 0 (
        echo Error: Failed to bootstrap pip in embedded Python
        exit /b 1
    )
)

echo Site-packages: %SITE_PACKAGES%
if not exist "%SITE_PACKAGES%" mkdir "%SITE_PACKAGES%"

"!PYTHON_BIN!" -m pip install --upgrade --target "%SITE_PACKAGES%" -r "%REQUIREMENTS_FILE%"
if !ERRORLEVEL! neq 0 (
    echo Error: Failed to install Python packages
    exit /b 1
)

REM Verify critical packages are importable by Blender's Python
"!PYTHON_BIN!" -c "import websocket; print('  websocket-client:', websocket.__version__)"
if !ERRORLEVEL! neq 0 (
    echo Error: websocket-client installed but not importable — site-packages path mismatch
    exit /b 1
)
echo Successfully installed and verified Python packages

echo.
echo ============================================================
echo === Build Complete at %TIME% ===
echo ============================================================
echo Run Mixar using: %BUILD_ENV_DIR%\bin\mixar.exe
echo ============================================================
exit /b 0
