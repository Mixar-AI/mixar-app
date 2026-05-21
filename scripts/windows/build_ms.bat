REM SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
REM
REM SPDX-License-Identifier: GPL-2.0-or-later

@echo off
REM Mixar Build Script - MSBuild (forced)
REM Forces Visual Studio MSBuild generator regardless of detection, then delegates to build.bat.
set "BUILD_WITH_NINJA=0"
call "%~dp0build.bat"
exit /b %ERRORLEVEL%
