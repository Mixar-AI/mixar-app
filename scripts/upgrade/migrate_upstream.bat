REM SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
REM
REM SPDX-License-Identifier: GPL-2.0-or-later

@echo off
REM Windows wrapper script for migrate_upstream.py
REM Orchestrates the complete upstream migration workflow

setlocal

REM Get script directory
set "SCRIPT_DIR=%~dp0"

REM Call the Python script with all arguments
python "%SCRIPT_DIR%migrate_upstream.py" %*

endlocal
