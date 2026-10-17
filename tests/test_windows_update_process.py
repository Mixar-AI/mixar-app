# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise updater argument parsing and error policy in real PowerShell.

Only the elevated installer boundary is substituted. No MSI is executed and
no administrator prompt appears; successful starts launch an argv recorder.
"""
import base64
import json
import os
import subprocess
import sys

import pytest

from mixar.modules.common.updates.core import win_installer


pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='Windows PowerShell integration')

RECORDER = """
import json, os, sys
from pathlib import Path
Path(os.environ['QA_INSTALL_ARGS']).write_text(json.dumps(sys.argv[1:]))
sys.exit(int(os.environ['QA_INSTALL_EXIT']))
"""

LAUNCH = """
function Start-Process {
    [CmdletBinding()]
    param($FilePath, $ArgumentList, $Verb, [switch]$Wait, [switch]$PassThru)
    if($FilePath -ne 'msiexec.exe' -or $Verb -ne 'RunAs' -or !$Wait -or !$PassThru)
        {throw 'Unexpected installer invocation'}
    Microsoft.PowerShell.Management\\Start-Process -FilePath $env:QA_PYTHON `
        -ArgumentList (@(([char]34 + $env:QA_RECORDER + [char]34)) + $ArgumentList) `
        -Wait -PassThru -WindowStyle Hidden
}
"""


def run_snippet(tmp_path, prefix, *, exit_code=0):
    recorder = tmp_path / 'record arguments.py'
    recorder.write_text(RECORDER, encoding='utf-8')
    result = tmp_path / 'arguments.json'
    installer = str(tmp_path / 'User Name' / 'Mixar Update.msi')
    log = str(tmp_path / 'User Name' / 'installer log.txt')
    env = dict(os.environ, QA_PYTHON=sys.executable, QA_RECORDER=str(recorder),
               QA_INSTALL_ARGS=str(result), QA_INSTALL_EXIT=str(exit_code),
               MSI=installer, MSILOG=log)
    encoded = base64.b64encode((prefix + win_installer._PS_INSTALL).encode('utf-16le')).decode()
    process = subprocess.run(
        ['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
        env=env, capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return process, result, installer, log


@pytest.mark.parametrize('exit_code', [0, 3010, 1603])
def test_paths_are_single_arguments_and_installer_status_is_preserved(tmp_path, exit_code):
    process, result, installer, log = run_snippet(tmp_path, LAUNCH, exit_code=exit_code)
    assert process.returncode == exit_code, process.stderr
    assert json.loads(result.read_text()) == [
        '/i', installer, '/qb!', '/norestart', 'REBOOT=ReallySuppress',
        'LAUNCHAPP=0', '/l*v', log,
    ]


@pytest.mark.parametrize('native_error, expected', [(1223, 1602), (5, 1)])
def test_launch_errors_never_report_success(tmp_path, native_error, expected):
    prefix = """
function Start-Process {
    [CmdletBinding()]
    param($FilePath, $ArgumentList, $Verb, [switch]$Wait, [switch]$PassThru)
    Write-Error -Exception ([System.ComponentModel.Win32Exception]::new(ERROR_CODE))
}
""".replace('ERROR_CODE', str(native_error))
    process, result, _, _ = run_snippet(tmp_path, prefix)
    assert process.returncode == expected, process.stderr
    assert not result.exists()


def test_missing_process_status_is_a_failure(tmp_path):
    prefix = """
function Start-Process {
    [CmdletBinding()]
    param($FilePath, $ArgumentList, $Verb, [switch]$Wait, [switch]$PassThru)
}
"""
    process, result, _, _ = run_snippet(tmp_path, prefix)
    assert process.returncode == 1
    assert not result.exists()


@pytest.mark.parametrize('cancelled', [False, True])
def test_generated_batch_records_outcome_and_keeps_cancelled_installer(tmp_path, cancelled):
    from tests.qa.windows_update_probe import run_batch_case

    run_batch_case(win_installer, tmp_path, sys.executable, cancelled=cancelled)
