# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise updater argument parsing and error policy in real PowerShell.

Only the elevated installer boundary is substituted. No MSI is executed and
no administrator prompt appears; successful starts launch an argv recorder.
The generated helper also runs its install-directory lock wait, the
registry-first relaunch, MSI error extraction and the signer pin
(``tests/qa/windows_update_probe.py``), and the native process table and
terminate run against real processes.
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
    if($FilePath -ne ($env:SYS32 + '\\msiexec.exe') -or $Verb -ne 'RunAs' -or !$Wait -or !$PassThru)
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
    system32 = os.path.join(os.environ['SystemRoot'], 'System32')
    env = dict(os.environ, QA_PYTHON=sys.executable, QA_RECORDER=str(recorder),
               QA_INSTALL_ARGS=str(result), QA_INSTALL_EXIT=str(exit_code),
               MSI=installer, MSILOG=log, SYS32=system32)
    encoded = base64.b64encode((prefix + win_installer._PS_INSTALL).encode('utf-16le')).decode()
    process = subprocess.run(
        [os.path.join(system32, 'WindowsPowerShell', 'v1.0', 'powershell.exe'),
         '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
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


def test_helper_waits_for_a_live_app_before_installing(tmp_path):
    from tests.qa.windows_update_probe import run_wait_case

    run_wait_case(win_installer, tmp_path, sys.executable, app_exits_after=5)


def test_helper_gives_up_on_an_app_that_never_exits(tmp_path):
    from tests.qa.windows_update_probe import run_wait_case

    run_wait_case(win_installer, tmp_path, sys.executable)


def test_lock_wait_names_the_holder_and_does_not_install(tmp_path):
    from tests.qa.windows_update_probe import run_lock_case

    run_lock_case(win_installer, tmp_path, sys.executable)


def test_lock_released_during_the_wait_installs(tmp_path):
    from tests.qa.windows_update_probe import run_lock_case

    run_lock_case(win_installer, tmp_path, sys.executable, release_after=10)


def test_finish_relaunches_the_registered_install_first(tmp_path):
    from tests.qa.windows_update_probe import run_finish_case

    assert 'msi_error' not in run_finish_case(win_installer, tmp_path)


def test_finish_records_the_msi_error(tmp_path):
    from tests.qa.windows_update_probe import run_finish_case

    record = run_finish_case(
        win_installer, tmp_path, install_exit='1603',
        msi_log_text='MSI (s) (A0:B4) [12:00:00:000]: Product: Mixar -- Error 1925. '
                     'You do not have sufficient privileges.\n')
    assert record['msi_error'] == '1925'


@pytest.mark.parametrize('matching', [True, False])
def test_reverify_accepts_only_the_pinned_signer(tmp_path, matching):
    from tests.qa.windows_update_probe import run_signer_case

    if run_signer_case(win_installer, tmp_path, sys.executable, matching=matching) is None:
        pytest.skip('no validly signed file to stand in for the installer')


def test_native_process_table_sees_this_process_and_its_child():
    from mixar.modules.common.updates.core import win_processes

    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                             creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        rows = {row['pid']: row for row in win_processes._process_table()}
        me, kid = rows[os.getpid()], rows[child.pid]
        assert me['ppid'] == os.getppid()
        assert os.path.isabs(me['path']) and isinstance(me['created'], int)
        assert kid['ppid'] == os.getpid() and kid['created'] >= me['created']
        assert kid['name'].lower().startswith('python')
        assert win_processes.terminate(win_processes.Holder(
            win_processes.OTHER, kid['name'], child.pid, kid['created']))
        child.wait(timeout=10)
    finally:
        child.kill()
