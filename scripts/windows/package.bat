REM SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
REM
REM SPDX-License-Identifier: GPL-2.0-or-later

@echo off
setlocal enabledelayedexpansion

REM Mixar MSI Installer Packaging Script for Windows
REM Uses CPack (WIX generator) already configured in CMake upstream.
REM
REM Prerequisites:
REM   - Successful build via build.bat (or build_ninja.bat / build_ms.bat)
REM   - WIX Toolset v3 installed (https://wixtoolset.org/docs/wix3/)
REM     or WIX v4+ with wix.exe on PATH
REM
REM Usage:
REM   package.bat              — package current environment (from mixar.json)
REM   package.bat Prod         — override environment
REM   package.bat Prod MyApp   — override environment and package name

echo ============================================================
echo Mixar Installer Packaging Script
echo ============================================================

REM --- Load Settings ---
set "SCRIPT_DIR=%~dp0"
call "%SCRIPT_DIR%settings.bat"
if %ERRORLEVEL% neq 0 (
    echo Error: Failed to load settings
    exit /b 1
)

REM --- Parse Arguments ---
if not "%~1"=="" set "MIXAR_ENV=%~1"
if not "%~2"=="" set "PACKAGE_NAME_OVERRIDE=%~2"

if "%MIXAR_ENV%"=="" (
    echo Warning: MIXAR_ENV is empty, defaulting to Prod
    set "MIXAR_ENV=Prod"
)

set "BUILD_ENV_DIR=%BUILD_DIR%\%MIXAR_ENV%"
set "INSTALLER_OUTPUT_DIR=%ROOT_DIR%\dist"

echo Environment : %MIXAR_ENV%
echo Build dir   : %BUILD_ENV_DIR%
echo Output dir  : %INSTALLER_OUTPUT_DIR%
echo App name    : %MIXAR_APP_NAME%
echo Version     : %MIXAR_VERSION%
echo.

REM --- [1/6] Verify Build Exists ---
echo [1/6] Verifying build artifacts...
if not exist "%BUILD_ENV_DIR%\bin\mixar.exe" (
    echo Error: Build not found at %BUILD_ENV_DIR%\bin\mixar.exe
    echo        Run build.bat first before packaging.
    exit /b 1
)
echo Build artifacts found.

REM --- Verify Python packages are installed ---
echo Verifying Python packages...
set "PY_BASE=%BUILD_ENV_DIR%\bin"
set "PKG_SITE_PACKAGES=%PY_BASE%\%BLENDER_VERSION%\python\lib\site-packages"
set "PKG_PYTHON_BIN="
for %%P in (
    "%PY_BASE%\%BLENDER_VERSION%\python\bin\python.exe"
    "%PY_BASE%\%BLENDER_VERSION%\python\bin\python3.exe"
) do (
    if exist "%%~P" (
        set "PKG_PYTHON_BIN=%%~P"
        goto :found_pkg_python
    )
)
:found_pkg_python
set "PKG_REQUIREMENTS=%SCRIPT_DIR%..\python_requirements.txt"
if defined PKG_PYTHON_BIN (
    if not exist "%PKG_SITE_PACKAGES%" mkdir "%PKG_SITE_PACKAGES%"
    echo Installing/verifying Python packages...
    "!PKG_PYTHON_BIN!" -m pip install --upgrade --target "%PKG_SITE_PACKAGES%" -r "%PKG_REQUIREMENTS%"
    if !ERRORLEVEL! neq 0 (
        echo Error: Failed to install required Python packages. Aborting packaging.
        exit /b 1
    )
    echo Python packages verified.
) else (
    echo Error: Python binary not found under %PY_BASE%\%BLENDER_VERSION%\python\bin
    echo        Cannot verify required packages. Aborting packaging.
    exit /b 1
)

REM --- [2/6] Verify WIX Toolset ---
echo [2/6] Checking for WIX Toolset...

set "WIX_FOUND="

REM Check WIX v3 (candle.exe / light.exe) — most common with CPack
where candle.exe >nul 2>&1
if !ERRORLEVEL! equ 0 (
    set "WIX_FOUND=1"
    echo WIX v3 detected on PATH.
)

REM Check WIX_ROOT environment variable (set by WIX v3 installer)
if not defined WIX_FOUND (
    if defined WIX (
        if exist "!WIX!bin\candle.exe" (
            set "WIX_FOUND=1"
            set "PATH=!WIX!bin;!PATH!"
            echo WIX v3 detected at: !WIX!
        )
    )
)

REM Search common WIX v3 install locations
if not defined WIX_FOUND (
    for /d %%W in ("%ProgramFiles(x86)%\WiX Toolset v3*") do (
        if exist "%%W\bin\candle.exe" (
            set "WIX_FOUND=1"
            set "PATH=%%W\bin;%PATH%"
            echo WIX v3 detected at: %%W
        )
    )
)

if not defined WIX_FOUND (
    echo.
    echo Error: WIX Toolset not found.
    echo.
    echo   Install WIX Toolset v3 from: https://wixtoolset.org/docs/wix3/
    echo   Or via winget:  winget install WixToolset.WiX --version 3.14.1
    echo   Or via choco:   choco install wixtoolset -y
    echo.
    echo   After installing, ensure candle.exe is on PATH or the WIX
    echo   environment variable is set.
    exit /b 1
)

REM --- [3/6] Verify CMake ---
echo [3/6] Verifying CMake availability...
where cmake >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo Error: CMake not found on PATH.
    exit /b 1
)
echo CMake found.

REM --- [4/6] Reconfigure CMake (packaging metadata) ---
echo [4/6] Reconfiguring CMake to refresh packaging metadata...
cmake "%BUILD_ENV_DIR%" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo Warning: CMake reconfigure returned non-zero, packaging may use stale metadata.
)

REM --- [5/6] Run CPack ---
echo [5/6] Generating MSI installer with CPack...
echo.

REM Determine architecture
if "%PROCESSOR_ARCHITECTURE%"=="AMD64" (
    set "PACKAGE_ARCH=x64"
) else if "%PROCESSOR_ARCHITECTURE%"=="ARM64" (
    set "PACKAGE_ARCH=arm64"
) else (
    set "PACKAGE_ARCH=%PROCESSOR_ARCHITECTURE%"
)

REM Build standardized package name: Mixar-{version}-{env}-{arch}
REM For Prod, omit the env name from the package filename
if not defined PACKAGE_NAME_OVERRIDE (
    if "%MIXAR_ENV%"=="Prod" (
        set "PACKAGE_NAME_OVERRIDE=Mixar-%MIXAR_VERSION%-%PACKAGE_ARCH%"
    ) else (
        set "PACKAGE_NAME_OVERRIDE=Mixar-%MIXAR_VERSION%-%MIXAR_ENV%-%PACKAGE_ARCH%"
    )
)

REM Use CPACK_INSTALLED_DIRECTORIES to package the entire bin/ directory as-is,
REM instead of re-running cmake --install which misses pip-installed packages.
set "BIN_DIR_FWD=%BUILD_ENV_DIR:\=/%/bin"

set "CPACK_ARGS=-G WIX"
set "CPACK_ARGS=%CPACK_ARGS% -B "%INSTALLER_OUTPUT_DIR%""
set "CPACK_ARGS=%CPACK_ARGS% -D CPACK_PACKAGE_FILE_NAME=%PACKAGE_NAME_OVERRIDE%"
set "CPACK_ARGS=%CPACK_ARGS% -D CPACK_INSTALL_CMAKE_PROJECTS="
set "CPACK_ARGS=%CPACK_ARGS% -D CPACK_INSTALLED_DIRECTORIES=%BIN_DIR_FWD%;."
echo Package name: %PACKAGE_NAME_OVERRIDE%

echo Running: cpack %CPACK_ARGS%
echo Working directory: %BUILD_ENV_DIR%
echo.

pushd "%BUILD_ENV_DIR%"
cpack %CPACK_ARGS%
set "CPACK_EXIT=%ERRORLEVEL%"
popd

if %CPACK_EXIT% neq 0 (
    echo.
    echo Error: CPack failed with exit code %CPACK_EXIT%
    echo.
    echo Common fixes:
    echo   - Ensure WIX Toolset v3 bin/ is on PATH
    echo   - Ensure the build completed successfully ^(build.bat^)
    echo   - Check CPack logs in: %INSTALLER_OUTPUT_DIR%\_CPack_Packages\
    exit /b 1
)

REM --- [6/6] Report Output ---
echo.
echo [6/6] Locating generated installer...

set "MSI_FILE=%INSTALLER_OUTPUT_DIR%\%PACKAGE_NAME_OVERRIDE%.msi"

if exist "!MSI_FILE!" (
    echo.
    echo ============================================================
    echo === Installer Created Successfully ===
    echo ============================================================
    echo MSI: !MSI_FILE!

    REM Show file size
    for %%A in ("!MSI_FILE!") do (
        set /a "SIZE_MB=%%~zA / 1048576"
        echo Size: !SIZE_MB! MB
    )

    echo.
    echo Install silently:  msiexec /i "!MSI_FILE!" /qn
    echo Install with UI:   msiexec /i "!MSI_FILE!"
    echo ============================================================
) else (
    echo Warning: No .msi file found in %INSTALLER_OUTPUT_DIR%
    echo Check CPack output above for details.
    exit /b 1
)

exit /b 0
