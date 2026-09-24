REM SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
REM
REM SPDX-License-Identifier: GPL-2.0-or-later

@echo off
setlocal enabledelayedexpansion

REM Initialize submodule to the exact commit specified by parent repo.
REM LFS smudge is skipped here so the initial checkout stays fast; the LFS
REM content is fetched explicitly further down.
echo Initializing Blender submodule...
set "GIT_LFS_SKIP_SMUDGE=1"
git submodule update --init --recursive --force --progress
if %errorlevel% neq 0 (
    echo Failed to initialize submodule
    exit /b 1
)

REM Re-enable LFS smudge for everything that follows. 'make update' checks out
REM lib/windows_x64 itself (build_files/windows/lib_update.cmd), and with smudge
REM still skipped it fills the library folder with LFS pointer files instead of
REM real binaries. find_dependencies.cmd then picks up the pointer as PYTHON
REM because it only tests 'if EXIST', and update_sources.cmd tries to execute
REM it -- which Windows reports as "This version of ... python.exe is not
REM compatible with the version of Windows you're running."
set "GIT_LFS_SKIP_SMUDGE="

cd upstream
if %errorlevel% neq 0 (
    echo Failed to enter the upstream directory
    exit /b 1
)

REM Call make.bat by explicit relative path, and via 'call'. Two reasons:
REM   - cmd does not search the current directory for executables when
REM     NoDefaultCurrentDirectoryInExePath is set (Git Bash and similar shells
REM     set it), so a bare 'make' is unresolvable even though make.bat is here.
REM   - without 'call', control transfers to make.bat and never returns, so
REM     everything below this line would silently be skipped.
echo Running make update...
call .\make.bat update
if %errorlevel% neq 0 (
    echo Failed: make update
    echo Try running 'make update' manually in the upstream directory.
    cd ..
    exit /b 1
)

REM Fetch LFS content. The platform libraries live in a NESTED submodule
REM (upstream/lib/windows_x64), and a pull in the parent repo never descends
REM into it, so pull inside the submodules as well.
echo Pulling LFS files...
git lfs pull
if %errorlevel% neq 0 (
    echo Failed: git lfs pull in upstream
    cd ..
    exit /b 1
)

git submodule foreach --recursive "git lfs pull"
if %errorlevel% neq 0 (
    echo Failed: git lfs pull in the upstream submodules
    cd ..
    exit /b 1
)

cd ..
echo Initialization complete!
exit /b 0
