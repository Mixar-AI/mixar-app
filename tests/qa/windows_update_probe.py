# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run the real Windows batch helper against an inert installer boundary.

No UAC prompt or MSI execution: Start-Process is shadowed only inside the
test PowerShell invocation. The successful case launches an argv recorder;
the failure case emits the real Win32 cancellation error. No app is relaunched.

Beyond the plain install: the install-directory lock wait (a python.exe kept
running from a fake install dir, with the wait shortened in the generated
script only), the registry-first relaunch and MSI error extraction of the
post-install PowerShell (Get-ItemProperty and Start-Process shadowed), and
the signer pin of the pre-install re-verify. Windows only; stdlib only, so
it imports anywhere.
"""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess

_NO_WINDOW = 0x08000000  # subprocess.CREATE_NO_WINDOW, defined on Windows only

SHIM = """
function Start-Process {
    [CmdletBinding()]
    param($FilePath, $ArgumentList, $Verb, [switch]$Wait, [switch]$PassThru)
    if($FilePath -ne ($env:SYS32 + '\\msiexec.exe') -or $Verb -ne 'RunAs' -or !$Wait -or !$PassThru)
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

# The post-install step's registry read and relaunch, made inert: one
# registered Mixar at %QA_LOCATION%, and a Start-Process that records its
# target instead of starting anything.
FINISH_SHIM = """
function Get-ItemProperty {
    [CmdletBinding()]
    param($Path)
    [pscustomobject]@{DisplayName='Mixar'; WindowsInstaller=1;
        DisplayVersion=$env:VERSION; InstallLocation=$env:QA_LOCATION}
}
function Start-Process {
    [CmdletBinding()]
    param($FilePath)
    Add-Content -LiteralPath $env:QA_STARTED -Value $FilePath
}
"""


def _record(path):
    """The helper's result file (PowerShell may append after a UTF-8 BOM)."""
    pairs = (line.split('=', 1) for line in
             Path(path).read_text(encoding='utf-8-sig').splitlines() if '=' in line)
    return {key.lstrip('\ufeff'): value for key, value in pairs}


def _system32():
    return os.path.join(os.environ.get('SystemRoot') or r'C:\Windows', 'System32')


def _powershell(script, env, timeout=30):
    encoded = base64.b64encode(script.encode('utf-16le')).decode()
    exe = os.path.join(_system32(), 'WindowsPowerShell', 'v1.0', 'powershell.exe')
    return subprocess.run(
        [exe, '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
        env=env, capture_output=True, timeout=timeout, creationflags=_NO_WINDOW,
    )


def _prepare(root, python, *, cancelled=False, installer_name='Mixar Update.msi'):
    root = Path(root).resolve() / 'User Name'
    root.mkdir(parents=True, exist_ok=True)
    msi = root / installer_name
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
    return root, msi, args_path, env


def _run_helper(module, root, msi, env, python, *, lock_wait_s=None, exit_wait_s=None,
                pid=None, timeout=60, **build):
    if pid is None:
        # PID 0 belongs to Windows' idle process; use our own exited process
        # to exercise the helper's actual wait-for-app-exit branch.
        parent = subprocess.Popen([str(python), '-c', 'pass'], creationflags=_NO_WINDOW)
        parent.wait(timeout=15)
        pid = parent.pid
    build.setdefault('require_signature', False)
    script = module.build_script(
        installer_path=str(msi), staging_dir=str(root), version='9.9.9', pid=pid,
        relaunch_candidates=[], **build,
    )
    if exit_wait_s is not None:
        # Test-only: the production 300 s wait for Mixar, shortened in this copy.
        line = f'if %WAITED% GEQ {module.HELPER_WAIT_FOR_EXIT_S} goto timeout'
        assert script.count(line) == 1
        script = script.replace(line, f'if %WAITED% GEQ {int(exit_wait_s)} goto timeout')
    assert script.count(module._PS_INSTALL) == 1
    script = script.replace(module._PS_INSTALL, '. $env:QA_SHIM;' + module._PS_INSTALL)
    # The shim refuses every non-msiexec Start-Process, so the registry-first
    # relaunch cannot start an installed Mixar on the QA machine.
    assert script.count(module._PS_FINISH) == 1
    script = script.replace(module._PS_FINISH, '. $env:QA_SHIM;' + module._PS_FINISH)
    if lock_wait_s is not None:
        # Test-only: the production 60 s lock wait, shortened in this copy.
        line = f'if %LOCKWAIT% GEQ {module.HELPER_WAIT_FOR_LOCKS_S} goto locked'
        assert script.count(line) == 1
        script = script.replace(line, f'if %LOCKWAIT% GEQ {int(lock_wait_s)} goto locked')
    script_path = root / 'helper.cmd'
    script_path.write_text(script, encoding='cp1252', newline='\r\n')
    process = subprocess.run(
        [os.path.join(_system32(), 'cmd.exe'), '/d', '/c', str(script_path)], env=env,
        cwd=root, capture_output=True, timeout=timeout, creationflags=_NO_WINDOW,
    )
    return process, _record(root / 'update-result.txt')


def _installed_arguments(args_path, msi, root):
    arguments = json.loads(args_path.read_text())
    assert arguments == [
        '/i', str(msi), '/qb!', '/norestart', 'REBOOT=ReallySuppress',
        'LAUNCHAPP=0', '/l*v', str(root / 'msi-install.log'),
    ], arguments
    return arguments


def run_batch_case(module, root, python, *, cancelled=False):
    root, msi, args_path, env = _prepare(root, python, cancelled=cancelled)
    process, record = _run_helper(module, root, msi, env, python, timeout=20)
    expected = '1602' if cancelled else '0'
    core = {key: record.get(key) for key in ('version', 'stage', 'exit', 'helper_version')}
    assert core == {'version': '9.9.9', 'stage': 'install', 'exit': expected,
                    'helper_version': str(module.HELPER_VERSION)}, record
    assert record.get('relaunch_kind') == 'none', record
    assert process.returncode == int(expected), (process.returncode, process.stderr)
    assert msi.exists() is cancelled
    arguments = None if cancelled else _installed_arguments(args_path, msi, root)
    return {'result': record, 'staging_dir': str(root),
            'installer_retained': msi.exists(), 'arguments': arguments}


def run_wait_case(module, root, python, *, app_exits_after=None):
    """A LIVE app PID: the helper must wait for it, or give up without installing.

    Every other case hands the helper an already-exited PID, which passes
    even when the tasklist | find check is broken — and a broken check
    reads as "exited" and installs over the running app.
    """
    root, msi, args_path, env = _prepare(root, python)
    app = subprocess.Popen(
        [str(python), '-c', f'import time; time.sleep({app_exits_after or 60})'],
        creationflags=_NO_WINDOW)
    try:
        process, record = _run_helper(
            module, root, msi, env, python, pid=app.pid,
            exit_wait_s=6 if app_exits_after is None else 60, timeout=120,
        )
    finally:
        app.kill()
    if app_exits_after is None:
        assert (record.get('stage'), record.get('exit')) == ('wait', 'timeout'), record
        assert msi.exists() and not args_path.exists(), record
    else:
        assert (record.get('stage'), record.get('exit')) == ('install', '0'), record
        assert int(record.get('wait_s', '0')) >= app_exits_after - 1, record
        _installed_arguments(args_path, msi, root)
    return {'result': record, 'returncode': process.returncode}


def start_holder(install_dir, python, seconds):
    """Keep a python.exe running FROM *install_dir* for *seconds*.

    A copy of *python* with the DLLs beside it (and a venv's pyvenv.cfg),
    pointed back at its standard library through PYTHONHOME.
    """
    source = Path(python).resolve()
    install_dir = Path(install_dir)
    install_dir.mkdir(parents=True, exist_ok=True)
    for item in [source, *source.parent.glob('*.dll')]:
        shutil.copy2(item, install_dir / item.name)
    for cfg in (source.parent / 'pyvenv.cfg', source.parent.parent / 'pyvenv.cfg'):
        if cfg.is_file():
            shutil.copy2(cfg, install_dir / 'pyvenv.cfg')
            break
    home = subprocess.run(
        [str(source), '-c', 'import sys; print(sys.base_prefix)'],
        capture_output=True, text=True, timeout=30, creationflags=_NO_WINDOW,
    ).stdout.strip()
    return subprocess.Popen(
        [str(install_dir / source.name), '-S', '-c', f'import time; time.sleep({seconds})'],
        env=dict(os.environ, PYTHONHOME=home), creationflags=_NO_WINDOW,
    )


def run_lock_case(module, root, python, *, release_after=None):
    """A process from the install dir holds it: locked, or installed once it exits."""
    root, msi, args_path, env = _prepare(root, python)
    install_dir = root / 'Mixar Install'
    # Locked: outlives the shortened wait. Released: exits within the real one.
    holder = start_holder(install_dir, python, release_after or 40)
    try:
        process, record = _run_helper(
            module, root, msi, env, python, install_dir=str(install_dir),
            lock_wait_s=6 if release_after is None else 60, timeout=120,
        )
    finally:
        holder.kill()
    if release_after is None:
        assert (record.get('stage'), record.get('exit')) == ('locked', 'locked'), record
        assert 'python.exe' in record.get('locks', '').lower().split(','), record
        assert msi.exists() and not args_path.exists(), record
    else:
        assert (record.get('stage'), record.get('exit')) == ('install', '0'), record
        assert int(record.get('wait_s', '0')) >= 3, record
        _installed_arguments(args_path, msi, root)
    return {'result': record, 'returncode': process.returncode}


def run_finish_case(module, root, *, install_exit='0', msi_log_text=None):
    """The post-install step alone: registry first, then the MSI's error."""
    root = Path(root).resolve() / 'User Name'
    location = root / 'Registered Mixar'
    location.mkdir(parents=True, exist_ok=True)
    (location / 'mixar-launcher.exe').write_bytes(b'MIXAR_QA_ONLY')
    msi_log = root / 'msi-install.log'
    if msi_log_text is not None:
        msi_log.write_text(msi_log_text, encoding='utf-8')
    result, started = root / 'update-result.txt', root / 'started.txt'
    env = dict(os.environ, VERSION='9.9.9', STAGE='install', INSTALL_EXIT=install_exit,
               MSILOG=str(msi_log), RELAUNCH='', RESULT=str(result),
               QA_LOCATION=str(location), QA_STARTED=str(started))
    process = _powershell(FINISH_SHIM + module._PS_FINISH, env)
    record = _record(result)
    launcher = str(location / 'mixar-launcher.exe')
    assert process.returncode == 0, process.stderr
    assert started.read_text(encoding='utf-8-sig').split() == [launcher], started
    assert record.get('relaunch_kind') == 'registry', record
    assert record.get('relaunch') == launcher, record
    assert (record.get('installed_version'), record.get('install_location')) == (
        '9.9.9', str(location)), record
    return record


def _signed_file(python):
    """``(path, thumbprint)`` of a validly Authenticode-signed file here, or None."""
    windows = os.environ.get('SystemRoot') or r'C:\Windows'
    for candidate in (str(python), os.path.join(windows, 'explorer.exe'),
                      os.path.join(_system32(), 'msiexec.exe')):
        process = _powershell(
            "$s=Get-AuthenticodeSignature -LiteralPath $env:QA_FILE;"
            "if($s.Status -eq 'Valid'){Write-Output $s.SignerCertificate.Thumbprint}",
            dict(os.environ, QA_FILE=candidate))
        thumbprint = process.stdout.decode('utf-8', 'replace').strip()
        if thumbprint:
            return candidate, thumbprint
    return None


def run_signer_case(module, root, python, *, matching):
    """The re-verify accepts only the pinned certificate; None if nothing here is signed."""
    signed = _signed_file(python)
    if signed is None:
        return None
    source, thumbprint = signed
    name = 'Mixar Update' + Path(source).suffix
    root, msi, args_path, env = _prepare(root, python, installer_name=name)
    shutil.copy2(source, msi)
    pin = thumbprint.lower() if matching else '0' * 40
    process, record = _run_helper(
        module, root, msi, env, python, require_signature=True, signer_thumbprint=pin)
    if matching:
        assert (record.get('stage'), record.get('exit')) == ('install', '0'), record
        _installed_arguments(args_path, msi, root)
    else:
        assert (record.get('stage'), record.get('exit')) == ('verify', 'signature'), record
        assert not args_path.exists() and not msi.exists(), record
    return {'result': record, 'signer': thumbprint, 'returncode': process.returncode}
