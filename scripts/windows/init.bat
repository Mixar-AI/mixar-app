REM SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
REM
REM SPDX-License-Identifier: GPL-2.0-or-later

@echo off
setlocal enabledelayedexpansion

REM Initialize submodule to the exact commit specified by parent repo
echo Initializing Blender submodule...
set "GIT_LFS_SKIP_SMUDGE=1"
git submodule update --init --recursive --force --progress
if %errorlevel% neq 0 (
    echo Failed to initialize submodule
    exit /b 1
)

cd upstream
REM Download LFS files using make update
echo Running make update...
make update
if %errorlevel% neq 0 (
    echo Try running 'make update' manually in the upstream directory to download LFS files
)

echo Pulling LFS files...
git lfs pull
if %errorlevel% neq 0 (
    echo Warning: git lfs pull failed
)

cd ..
echo Initialization complete!
exit /b 0
