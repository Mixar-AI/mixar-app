# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Shortcuts After the Move Out of Program Files (#2079)

The update that moves Mixar from ``C:\\Program Files\\Mixar`` into
``%LocalAppData%\\Programs\\Mixar`` re-creates its own Start menu and
desktop shortcuts, but a taskbar pin (or a shortcut the user made) still
aims at the Program Files launcher. The first start after the move
repoints them, once.

Only ``.lnk`` files whose target is a Mixar launcher directly in the old
folder, and whose counterpart exists in the new folder, are touched:
target, working directory and icon move along, nothing else changes.
Whether the old launcher still exists does not matter (a file held during
the move goes only at the next restart). Folders scanned: the taskbar pins and implicit pins
(``Quick Launch``, recursive), the user's Start menu programs (recursive)
and the desktop (top level only). Hidden folders count: the pins live in
``Quick Launch\\User Pinned``, which Windows marks hidden. The "Open with"
entries (:mod:`assoc_repair`) and the GPU chosen for Mixar in Windows'
graphics settings (:mod:`gpu_preference`) go along.

The trigger is the HKCU value only an install that put Mixar elsewhere
writes, naming the old folder (``win_scope.moved_from``); the per-user
config records the install it ran for, so it runs once whatever it finds.
The work is one hidden PowerShell (``WScript.Shell``, which reads and
writes ``.lnk`` files) on a worker thread. Nothing here needs ``bpy``.
"""

import base64
import ntpath
import os
import subprocess
import threading

from mixar.config.logging_config import get_logger

from ..constants import SHORTCUTS_REPAIRED_CONFIG_KEY

logger = get_logger(__name__)

_TIMEOUT_S = 120

# Paths reach the script through the environment, never its text.
_PS_REPAIR = r"""
$ErrorActionPreference='Stop'
$old=$env:MIXAR_OLD_DIR.TrimEnd('\')+'\'
$new=$env:MIXAR_NEW_DIR.TrimEnd('\')+'\'
$names=@('mixar-launcher.exe','mixar.exe','blender-launcher.exe')
$app=[Environment]::GetFolderPath('ApplicationData')
$roots=@(
  @((Join-Path $app 'Microsoft\Internet Explorer\Quick Launch'),$true),
  @((Join-Path $app 'Microsoft\Windows\Start Menu\Programs'),$true),
  @([Environment]::GetFolderPath('Desktop'),$false))
$sh=New-Object -ComObject WScript.Shell
$n=0
foreach($r in $roots){
  if(-not $r[0] -or -not (Test-Path -LiteralPath $r[0])){continue}
  $files=@(Get-ChildItem -LiteralPath $r[0] -Filter *.lnk -File -Force -Recurse:([bool]$r[1]) -ErrorAction SilentlyContinue)
  foreach($f in $files){
    try{
      $l=$sh.CreateShortcut($f.FullName)
      $t=[string]$l.TargetPath
      if(-not $t.StartsWith($old,[StringComparison]::OrdinalIgnoreCase)){continue}
      $b=$t.Substring($old.Length)
      if($b.Contains('\') -or ($names -notcontains $b.ToLower())){continue}
      $nt=$new+$b
      if(-not (Test-Path -LiteralPath $nt -PathType Leaf)){continue}
      $l.TargetPath=$nt
      if(([string]$l.WorkingDirectory).TrimEnd('\') -ieq $old.TrimEnd('\')){$l.WorkingDirectory=$new.TrimEnd('\')}
      $i=[string]$l.IconLocation
      if($i.StartsWith($old,[StringComparison]::OrdinalIgnoreCase)){$l.IconLocation=$new+$i.Substring($old.Length)}
      $l.Save()
      $n++
      Write-Output ('repointed '+$f.Name)
    }catch{Write-Output ('skipped '+$f.Name+': '+$_.Exception.Message)}
  }
}
Write-Output ('count='+$n)
"""


def should_repair(install_dir, moved_from, done_for) -> bool:
    """Pure: after a move from *moved_from* into *install_dir*, not yet run
    for it."""
    from .app_paths import is_within

    if not moved_from or not install_dir:
        return False
    if is_within(install_dir, moved_from):
        return False
    return ntpath.normcase(str(done_for or "")) != ntpath.normcase(install_dir)


def maybe_repair_after_move(install_dir) -> bool:
    """Start the one repair after a move, if it is due. Main thread, cheap:
    one registry read and the config. Returns True when it started."""
    if os.name != "nt":
        return False
    from mixar.config.config import add_config, get_config

    from .win_scope import moved_from

    old_dir = moved_from()
    if not should_repair(install_dir, old_dir, get_config().get(SHORTCUTS_REPAIRED_CONFIG_KEY)):
        return False
    # Recorded first: whatever the scan finds, it never runs again for this
    # install (a PowerShell per launch would cost every user something).
    add_config(SHORTCUTS_REPAIRED_CONFIG_KEY, install_dir)
    threading.Thread(
        target=_run, args=(old_dir, install_dir),
        name="MixarShortcutRepair", daemon=True,
    ).start()
    return True


def _run(old_dir, new_dir) -> None:
    from .app_paths import windows_system_dir
    from .assoc_repair import repair_open_with
    from .gpu_preference import repair_gpu_preference

    for repair, what in ((repair_open_with, "repoint the Open with entries"),
                         (repair_gpu_preference, "carry the GPU preference over")):
        try:
            repair(old_dir, new_dir)
        except Exception:  # noqa: BLE001 - the shortcuts still follow
            logger.warning("Could not %s after the move", what, exc_info=True)

    powershell = ntpath.join(windows_system_dir(), "WindowsPowerShell", "v1.0", "powershell.exe")
    encoded = base64.b64encode(_PS_REPAIR.encode("utf-16-le")).decode("ascii")
    env = dict(os.environ, MIXAR_OLD_DIR=old_dir, MIXAR_NEW_DIR=new_dir)
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv, our own script
            [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-EncodedCommand", encoded],
            env=env, capture_output=True, text=True, timeout=_TIMEOUT_S,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("Could not repoint shortcuts after the move: %s", e)
        return
    lines = [line.strip() for line in (done.stdout or "").splitlines() if line.strip()]
    logger.info("Shortcut repair after the move (exit %s): %s", done.returncode,
                "; ".join(lines[-20:]) or "no output")
