REM SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
REM
REM SPDX-License-Identifier: GPL-2.0-or-later

@echo off
REM Windows wrapper script for checkout_upstream.py
REM This script simply calls the Python implementation

setlocal

REM Get script directory
set "SCRIPT_DIR=%~dp0"

REM Call the Python script with all arguments
python "%SCRIPT_DIR%checkout_upstream.py" %*

endlocal
