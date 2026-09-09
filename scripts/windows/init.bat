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

REM LFS content is fetched explicitly below, so let the smudge filter run again.
set "GIT_LFS_SKIP_SMUDGE="

REM Deliberately NOT calling upstream's "make update" here. It runs
REM make_update.py, which does "git merge --ff-only upstream/<branch>" and would
REM drag the submodule off the exact commit pinned above; its lib_update.cmd also
REM prompts interactively on failure. Its only job we need is the LFS download,
REM which the explicit pulls below do directly.
echo Pulling LFS files...
git lfs pull
if %errorlevel% neq 0 (
    echo Warning: git lfs pull failed
)

REM The platform libraries live in a nested submodule (lib/<platform>) with its
REM own LFS endpoint; the pull above does not reach it, so files there would
REM stay as 133-byte pointer stubs and the build would fail on missing libs.
echo Pulling LFS files for platform libraries...
git submodule foreach "git lfs pull"
if %errorlevel% neq 0 (
    echo Warning: git lfs pull failed for platform libraries
)

cd ..
echo Initialization complete!
exit /b 0
