# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Windows Update Helper

Writes and launches the detached batch script that applies a staged MSI
after Mixar exits.

Design notes, each one a failure this replaces:

- **The helper cannot live in the install directory.**  The MSI replaces
  everything there, so a helper running from it would be deleted (or
  block the upgrade) mid-install.  It runs out of the staging directory,
  driven by ``cmd.exe`` from ``System32``.
- **It waits for our PID, not for a fixed delay.**  Windows Installer
  refuses to replace files that are still open, and a sleep long enough
  to be safe is long enough to feel broken.
- **Then it ends Mixar connectors and waits for everything else running
  from the install directory.**  A file in use is not an error to msiexec:
  it defers the replacement to the next reboot and returns 3010, and the
  relaunch starts the old build.  An AI app respawns its MCP server (our
  ``python.exe``) on its next tool call, so one may appear after the app's
  own pre-quit check; connectors hold no user work and are stale once
  Mixar restarts, so the helper ends them (helper v4) — a python started by
  a Mixar is background work and is left alone.  For anything else the
  helper waits (bounded) and records ``stage=locked`` with the process
  basenames rather than installing; it never closes a window.
- **Elevation is explicit, and only where it is needed** (helper v7,
  ``win_scope``).  A per-user install runs msiexec as the user, with no
  prompt; a 1625 after a click is retried once with it. Otherwise
  ``Start-Process -Verb RunAs`` raises the UAC prompt and reports whether
  the user accepted, instead of letting ``msiexec`` fail with 1925 in the
  cases where it will not self-elevate; a machine install gets
  ``ALLUSERS=1``. Plain ``msiexec`` remains the fallback when PowerShell is
  unavailable.
- **It never shows a modal installer prompt.**  Under ``/qb!`` a file held
  from outside the install dir (antivirus, a service) stopped the update
  on Restart Manager's files-in-use dialog, twice (#2060). ``/passive``
  keeps the progress bar and closes holders, else replaces at reboot (3010).
- **The app always comes back — from where the MSI installed it.**
  Relaunch runs whatever the installer returned (a declined UAC prompt
  must leave the user with the version they already had), and prefers the
  Uninstall key's ``InstallLocation`` over the guessed candidates, which
  remain the fallback when PowerShell cannot run. An install on quit
  (helper v6, ``RELAUNCHMODE=0``; per-user installs only) leaves Mixar
  closed and records ``relaunch_kind=skipped`` — unless a launch was
  turned away meanwhile.
- **The outcome is written down.**  ``update-result.txt`` is the only way
  the relaunched app can tell the user that an update it started did not
  finish.  Beyond ``version``/``stage``/``exit`` it carries the attempt
  id, the version updated from, seconds waited, Windows Installer's
  version/location, the MSI's first ``Error NNNN`` and scope refusal, how
  msiexec was elevated and what was relaunched
  (see ``installer.classify_result``). The
  previous attempt's MSI log is moved to ``msi-install.prev.log`` right
  before the installer runs again.
- **Nothing is looked up by name** (helper v3).  cmd.exe searches the
  current directory — the staging directory, writable by every local
  account — before ``PATH``, so every tool runs by its System32 path, and
  ``cmd.exe`` itself is started by absolute path with AutoRun off (``/d``).
  Delayed expansion is forced off: a registry ``DelayedExpansion=1``
  would strip any ``!`` from a path.
- **It clears the update-in-progress marker** (``install_marker``) on
  every exit path, right before the relaunch: while it names this helper,
  a Mixar opened by hand quits instead of purging this very script.
- **The re-check pins the signer.**  Just before installing, the MSI must
  still be validly signed by the certificate whose thumbprint the app
  verified (``%SIGNER%``), not merely by anyone, and when the app is
  validly signed itself (always, for an install on quit or at launch),
  that certificate must carry the app's own signer subject
  (``%SIGNERSUBJECT%``, exact).

- **Every path arrives through the environment** (helper v8). cmd.exe
  reads a batch file in the console's OEM code page, and every per-user
  path holds the profile name: "José" written into the script came back as
  "JosÚ", and the helper wrote its result to a folder that does not exist.
  ``launch`` passes the paths, version and attempt id to cmd.exe as
  (Unicode) environment variables and the script text stays ASCII; the
  script only ever uses them quoted. Start-Process still joins its
  ArgumentList into one command line, so each path needs explicit quotes.
"""

import ntpath
import os
import re
import string
import subprocess

from mixar.config.logging_config import get_logger

from ..constants import (
    HELPER_LOG_NAME,
    HELPER_MARKER_NAME,
    HELPER_RESULT_NAME,
    HELPER_REOPEN_GRACE_S,
    HELPER_REOPEN_NAME,
    HELPER_REOPEN_WAIT_S,
    HELPER_VERSION,
    HELPER_WAIT_FOR_EXIT_S,
    HELPER_WAIT_FOR_LOCKS_S,
    MSI_LOG_NAME,
    MSI_PREV_LOG_NAME,
    MSI_UPGRADE_CODE,
    TRIGGER_CLICK,
    TRIGGERS,
)
from .app_paths import windows_system_dir
from .win_helper_cmd import _SCRIPT_TEMPLATE, _SIGNATURE_CHECK
# The PowerShell steps; re-exported because the tests read them from here.
from .win_helper_ps import (  # noqa: F401
    _PS_END_CONNECTORS,
    _PS_FINISH,
    _PS_HELD_VERIFY,
    _PS_HOLD,
    _PS_INSTALL,
    _PS_LOCKS,
    _PS_VERIFY,
)

logger = get_logger(__name__)

# CREATE_NO_WINDOW, not DETACHED_PROCESS: detached gives cmd.exe no console
# at all, so every console child the wait loop spawns each second (tasklist,
# find, ping, powershell) allocates its own brand-new VISIBLE window — the
# user watches terminals flash for the whole wait. A hidden console is
# inherited by all of them and nothing ever shows.
_CREATE_NO_WINDOW = 0x08000000
_CREATE_NEW_PROCESS_GROUP = 0x00000200
# If Mixar itself runs inside a kill-on-close job object (some launchers and
# IDEs do this), a child in the same job dies the moment Mixar quits — which
# is exactly when the helper's work starts. Breakaway is attempted first and
# dropped if the job forbids it.
_CREATE_BREAKAWAY_FROM_JOB = 0x01000000

# Characters that would break out of batch quoting. Paths are ours or come
# from environment variables, so this is a guard rather than a limitation:
# if one ever trips we fall back to the browser download instead of writing
# a script that does something unintended.
_UNSAFE_BATCH_CHARS = ('"', "%", "^", "&", "|", "<", ">", "\r", "\n")
# msiexec PROPERTY=value pairs the plan may add (ALLUSERS=1): nothing a
# batch line or PowerShell could read as anything else.
_MSI_PROPERTIES = re.compile(r"(?:[A-Z][A-Z0-9_]*=[A-Za-z0-9_.]*(?: |$))*")
# Version and attempt id are echoed unquoted into the log.
_PLAIN_VALUE = re.compile(r"[A-Za-z0-9._+-]*")
# The batch fallback relaunches at most this many candidates (RELAUNCH1..9).
_MAX_RELAUNCH_CANDIDATES = 9

_POWERSHELL = '"%PWSH%" -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command'

def _is_batch_safe(*values) -> bool:
    return not any(
        char in str(value) for value in values for char in _UNSAFE_BATCH_CHARS
    )


def _relaunch_block(count) -> str:
    """Batch fallback that starts the first of RELAUNCH1..*count* that exists.

    The paths are environment variables, used quoted, and each candidate is
    its own goto step: no parenthesised block whose end a path could cut.
    """
    lines = []
    for index in range(1, min(count, _MAX_RELAUNCH_CANDIDATES) + 1):
        lines += [
            f'if not defined RELAUNCH{index} goto relaunch{index}_next',
            f'if not exist "%RELAUNCH{index}%" goto relaunch{index}_next',
            f'start "" "%RELAUNCH{index}%"',
            '>>"%RESULT%" echo relaunch_kind=fallback',
            'goto relaunched',
            f':relaunch{index}_next',
        ]
    return "\n".join(lines)


def _hex(value) -> str:
    """A certificate thumbprint reduced to hex digits (it is embedded in the script)."""
    return "".join(char for char in str(value or "") if char in string.hexdigits).upper()


def build_script(
    *,
    installer_path,
    staging_dir,
    version,
    pid,
    relaunch_candidates,
    require_signature,
    signer_thumbprint="",
    signer_subject="",
    install_dir="",
    from_version="",
    attempt_id="",
    system_dir="",
    relaunch=True,
    trigger=TRIGGER_CLICK,
    elevate=True,
    elevate_fallback=False,
    msi_properties="",
):
    """Return the helper batch script text (pure — exercised directly by tests).

    The text is ASCII and names no path: those (and *signer_subject*) reach
    the script through :func:`helper_environment` (same arguments). *relaunch* False is an
    install on quit: Mixar is reopened only for a launch that was turned
    away while the helper worked. *elevate*, *elevate_fallback* and
    *msi_properties* are ``win_scope``'s plan.
    """
    if trigger not in TRIGGERS:
        raise ValueError(f"Unknown update trigger: {trigger!r}")
    if not _MSI_PROPERTIES.fullmatch(msi_properties or ""):
        raise ValueError(f"Unexpected msiexec properties: {msi_properties!r}")
    return _SCRIPT_TEMPLATE.format(
        system_dir=system_dir or windows_system_dir(),
        reopen_wait_s=int(HELPER_REOPEN_WAIT_S),
        reopen_grace_s=int(HELPER_REOPEN_GRACE_S),
        relaunch_mode="1" if relaunch else "0",
        trigger=trigger,
        pid=int(pid),
        elevate="1" if elevate else "0",
        elevate_fallback="1" if elevate_fallback and not elevate else "0",
        msi_properties=msi_properties or "",
        upgrade_code=MSI_UPGRADE_CODE,
        wait_s=int(HELPER_WAIT_FOR_EXIT_S),
        lock_wait_s=int(HELPER_WAIT_FOR_LOCKS_S),
        helper_version=int(HELPER_VERSION),
        powershell=_POWERSHELL,
        signature_check=(
            _SIGNATURE_CHECK.format(
                powershell=_POWERSHELL, ps_verify=_PS_VERIFY, signer=_hex(signer_thumbprint))
            if require_signature else ""
        ),
        ps_install=_PS_HOLD + (_PS_HELD_VERIFY if require_signature else "") + _PS_INSTALL,
        ps_end_connectors=_PS_END_CONNECTORS,
        ps_locks=_PS_LOCKS,
        ps_finish=_PS_FINISH,
        relaunch=_relaunch_block(len(relaunch_candidates)),
    )


def helper_environment(
    *,
    installer_path,
    staging_dir,
    version,
    relaunch_candidates,
    install_dir="",
    from_version="",
    attempt_id="",
    signer_subject="",
    **_plan,
) -> dict:
    """The helper's paths and free-text values, by variable name (pure).

    Passed to cmd.exe as environment variables, which Windows hands over
    as Unicode whatever the console code page: the profile name in every
    per-user path survives, where text inside the script would not.
    Accepts (and ignores) :func:`build_script`'s other arguments, so both
    can be called with one set.
    """
    candidates = [path for path in relaunch_candidates if path][:_MAX_RELAUNCH_CANDIDATES]
    join = ntpath.join  # Windows paths, whatever runs the tests
    env = {
        "LOG": join(staging_dir, HELPER_LOG_NAME),
        "MSI": installer_path,
        "MSILOG": join(staging_dir, MSI_LOG_NAME),
        "MSIPREVLOG": join(staging_dir, MSI_PREV_LOG_NAME),
        "RESULT": join(staging_dir, HELPER_RESULT_NAME),
        "LOCKS": join(staging_dir, "mixar-update-locks.txt"),
        "MARKER": join(staging_dir, HELPER_MARKER_NAME),
        "REOPEN": join(staging_dir, HELPER_REOPEN_NAME),
        "ELEVNOTE": join(staging_dir, "mixar-update-elevation.txt"),
        "INSTALLDIR": install_dir or "",
        "RELAUNCH": "|".join(candidates),
        "VERSION": version,
        "FROM_VERSION": from_version or "",
        "ATTEMPT": attempt_id or "",
        # Read only by PowerShell ($env:), so no character of it is special.
        "SIGNERSUBJECT": signer_subject or "",
    }
    for index in range(1, _MAX_RELAUNCH_CANDIDATES + 1):
        env[f"RELAUNCH{index}"] = candidates[index - 1] if index <= len(candidates) else ""
    return env


def _child_environment(values) -> dict:
    """This process's environment plus *values*; an empty value is removed
    (cmd's ``if defined`` and ``"%X%"==""`` then read it as unset)."""
    env = {key.upper(): value for key, value in os.environ.items()}
    for key, value in values.items():
        if value:
            env[key] = value
        else:
            env.pop(key, None)
    return env


def launch(
    *,
    installer_path,
    staging_dir,
    version,
    relaunch_candidates,
    require_signature=False,
    signer_thumbprint="",
    signer_subject="",
    install_dir="",
    from_version="",
    attempt_id="",
    relaunch=True,
    trigger=TRIGGER_CLICK,
    elevate=True,
    elevate_fallback=False,
    msi_properties="",
):
    """Write the helper script and start it detached.

    Returns the helper's ``subprocess.Popen``.

    Raises:
        OSError: the script could not be written or started — the caller
            must not quit the app.
        ValueError: a value could not be safely used by a batch script.
    """
    candidates = [path for path in relaunch_candidates if path]
    system_dir = windows_system_dir()
    if not _is_batch_safe(installer_path, staging_dir, install_dir, system_dir, *candidates):
        raise ValueError("Update paths contain characters unsafe for a batch script")
    if not all(_PLAIN_VALUE.fullmatch(str(value or ""))
               for value in (version, from_version, attempt_id)):
        raise ValueError("Update version or attempt id contains unexpected characters")

    arguments = dict(
        installer_path=installer_path,
        staging_dir=staging_dir,
        version=version,
        relaunch_candidates=candidates,
        require_signature=require_signature,
        signer_thumbprint=signer_thumbprint,
        signer_subject=signer_subject if require_signature else "",
        install_dir=install_dir,
        from_version=from_version,
        attempt_id=attempt_id,
        relaunch=relaunch,
        trigger=trigger,
        elevate=elevate,
        elevate_fallback=elevate_fallback,
        msi_properties=msi_properties,
    )
    script = build_script(pid=os.getpid(), system_dir=system_dir, **arguments)
    script_path = os.path.join(staging_dir, f"mixar-update-{version}.cmd")
    # ASCII by construction (every path is in the environment); strict, so a
    # regression fails here instead of writing a script cmd would misread.
    with open(script_path, "w", encoding="ascii", newline="\r\n") as handle:
        handle.write(script)

    popen_kwargs = dict(
        cwd=staging_dir,
        env=_child_environment(helper_environment(**arguments)),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    # Absolute, like every tool the script runs; /d skips any AutoRun
    # command (clink, a cd) the user's cmd.exe registry settings add.
    argv = [ntpath.join(system_dir, "cmd.exe"), "/d", "/c", script_path]
    flags = _CREATE_NO_WINDOW | _CREATE_NEW_PROCESS_GROUP
    try:
        proc = subprocess.Popen(  # noqa: S603 - fixed argv, our own script
            argv, creationflags=flags | _CREATE_BREAKAWAY_FROM_JOB, **popen_kwargs,
        )
    except OSError:
        # The job we run in forbids breakaway — spawn inside it and hope it
        # is not kill-on-close; refusing to update over this would be worse.
        proc = subprocess.Popen(  # noqa: S603 - fixed argv, our own script
            argv, creationflags=flags, **popen_kwargs,
        )
    logger.info("Windows update helper started: %s (pid %s)", script_path, proc.pid)
    return proc
