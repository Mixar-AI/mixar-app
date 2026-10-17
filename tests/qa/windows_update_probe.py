# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run the real Windows batch helper against an inert installer boundary.

No UAC prompt or MSI execution: Start-Process is shadowed only inside the
test PowerShell invocation. The successful case launches an argv recorder;
the failure case emits the real Win32 cancellation error. No app is relaunched.
"""
import json
import os
from pathlib import Path
import subprocess


SHIM = """
function Start-Process {
    [CmdletBinding()]
    param($FilePath, $ArgumentList, $Verb, [switch]$Wait, [switch]$PassThru)
    if($FilePath -ne 'msiexec.exe' -or $Verb -ne 'RunAs' -or !$Wait -or !$PassThru)
        {throw 'Unexpected installer invocation'}
    if($env:QA_CANCEL -eq '1') {
        Write-Error -Exception ([System.ComponentModel.Win32Exception]::new(1223))
        return
    }
    Microsoft.PowerShell.Management\\Start-Process -FilePath $env:QA_PYTHON `
        -ArgumentList (@(([char]34 + $env:QA_RECORDER + [char]34)) + $ArgumentList) `
        -Wait -PassThru -WindowStyle Hidden
}
"""

RECORDER = """
import json, os, sys
from pathlib import Path
Path(os.environ['QA_INSTALL_ARGS']).write_text(json.dumps(sys.argv[1:]))
"""


def run_batch_case(module, root, python, *, cancelled=False):
    root = Path(root).resolve() / 'User Name'
    root.mkdir(parents=True, exist_ok=True)
    msi = root / 'Mixar Update.msi'
    # This file is deliberately not an installer. Only it may be deleted by
    # the helper's success branch; the elevated execution boundary is inert.
    msi.write_bytes(b'MIXAR_QA_ONLY')
    recorder = root / 'record arguments.py'
    recorder.write_text(RECORDER, encoding='utf-8')
    shim = root / 'installer shim.ps1'
    shim.write_text(SHIM, encoding='utf-8-sig')
    args_path = root / 'arguments.json'
    env = dict(os.environ, QA_PYTHON=str(python), QA_RECORDER=str(recorder),
               QA_INSTALL_ARGS=str(args_path), QA_CANCEL='1' if cancelled else '0',
               QA_SHIM=str(shim))
    # PID 0 belongs to Windows' idle process; use our own exited process to
    # exercise the helper's actual wait-for-app-exit branch.
    parent = subprocess.Popen([str(python), '-c', 'pass'],
                              creationflags=subprocess.CREATE_NO_WINDOW)
    parent.wait(timeout=5)
    script = module.build_script(
        installer_path=str(msi), staging_dir=str(root), version='9.9.9', pid=parent.pid,
        relaunch_candidates=[], require_signature=False,
    )
    assert script.count(module._PS_INSTALL) == 1
    script = script.replace(module._PS_INSTALL, '. $env:QA_SHIM;' + module._PS_INSTALL)
    script_path = root / 'helper.cmd'
    script_path.write_text(script, encoding='cp1252', newline='\r\n')
    process = subprocess.run(
        ['cmd.exe', '/d', '/c', str(script_path)], env=env, cwd=root,
        capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    result_path = root / 'update-result.txt'
    record = dict(line.split('=', 1) for line in result_path.read_text().splitlines())
    expected = '1602' if cancelled else '0'
    assert record == {'version': '9.9.9', 'stage': 'install', 'exit': expected}, record
    assert process.returncode == int(expected), (process.returncode, process.stderr)
    assert msi.exists() is cancelled
    arguments = None
    if not cancelled:
        arguments = json.loads(args_path.read_text())
        assert arguments == [
            '/i', str(msi), '/qb!', '/norestart', 'REBOOT=ReallySuppress',
            'LAUNCHAPP=0', '/l*v', str(root / 'msi-install.log'),
        ], arguments
    return {'result': record, 'staging_dir': str(root),
            'installer_retained': msi.exists(), 'arguments': arguments}
