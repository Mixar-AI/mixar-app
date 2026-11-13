# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Windows Install Scope: How the Updater Runs msiexec

THE place the app decides, for the copy it runs from, whether an update
needs an administrator and how the helper starts the installer (#2079).
The installer's own refusals live in WIX.template ("SCOPE REFUSALS").

:func:`decide` is pure; :func:`plan_for` feeds it this machine's facts
(:mod:`win_msi`) and what earlier attempts learned (per-user config):

- **per-user, in this user's profile**: msiexec runs as the user with no
  prompt (``needs_elevation`` False, so it may also install on quit or at
  launch). After a click, a 1625 (Windows policy) is retried once with the
  prompt, but only when the prompt would elevate THIS account.
- **per-user, policy refuses installs without an administrator**
  (``DisableMSI``, Windows Server's default, or a 1625 seen before): the
  prompt every time, and only for an account that can elevate itself;
  anyone else gets the download.
- **per-machine** (an IT install made with ``ALLUSERS=1``): the prompt and
  ``ALLUSERS=1``, so Windows Installer upgrades that product instead of
  adding a per-user copy beside it.
- **anything else** (a per-user product outside the profile, which is how
  every release before #2079 installed into Program Files, or a scope
  Windows Installer could not tell): the prompt, as before. Run elevated,
  the new MSI moves a Program Files install into the user's profile.

Nothing here needs ``bpy``.
"""

import os
from collections import namedtuple

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import n_

from ..constants import (
    INSTALLER_REFUSED_CONFIG_KEY,
    MIXAR_REGISTRY_KEY,
    MOVED_FROM_VALUE,
    MSI_REFUSALS,
    USER_INSTALLS_BLOCKED_CONFIG_KEY,
)
from .win_msi import SCOPE_MACHINE, SCOPE_PER_USER

logger = get_logger(__name__)

# scope: "per_user", "machine" or "" (unknown). elevate: the helper starts
# msiexec with the UAC prompt. elevate_fallback: a 1625 from an unelevated
# msiexec is retried once with the prompt. msi_properties: appended to the
# msiexec line. blocked_reason: not empty when this account cannot install
# the update at all (offered as a download).
ScopePlan = namedtuple(
    "ScopePlan",
    "scope needs_elevation elevate elevate_fallback msi_properties blocked_reason",
)

POLICY_NEEDS_ADMIN = n_(
    "Windows on this computer allows installing only with an administrator. "
    "Download the update and ask your administrator to install it")


def decide(scope, install_dir, profile_dirs, *, user_installs_blocked,
           can_self_elevate) -> ScopePlan:
    """How to run the installer for the copy in *install_dir* (pure)."""
    from .app_paths import is_within

    in_profile = any(is_within(install_dir, root) for root in profile_dirs if root)
    if scope == SCOPE_PER_USER and in_profile:
        if not user_installs_blocked:
            return ScopePlan(scope, False, False, bool(can_self_elevate), "", "")
        if can_self_elevate:
            return ScopePlan(scope, True, True, False, "", "")
        return ScopePlan(scope, True, True, False, "", POLICY_NEEDS_ADMIN)
    if scope == SCOPE_MACHINE:
        return ScopePlan(scope, True, True, False, "ALLUSERS=1", "")
    return ScopePlan(scope or "", True, True, False, "", "")


def plan_for(scope, install_dir) -> ScopePlan:
    """:func:`decide` with this machine's facts; never raises."""
    from . import win_msi

    blocked = learned_user_installs_blocked()
    if blocked and scope == SCOPE_PER_USER:
        try:
            if forget_when_policy_allows(win_msi.disable_msi_value()):
                blocked = False
        except Exception:  # noqa: BLE001 - keep what was learned
            logger.debug("Could not re-read the Windows Installer policy", exc_info=True)
    if not blocked and scope == SCOPE_PER_USER:
        try:
            blocked = win_msi.user_installs_blocked_by_policy()
        except Exception:  # noqa: BLE001 - unknown: try without, the helper falls back
            logger.debug("Could not read the Windows Installer policy", exc_info=True)
    return decide(
        scope, install_dir, win_msi.profile_dirs(),
        user_installs_blocked=blocked,
        can_self_elevate=win_msi.can_self_elevate() if scope == SCOPE_PER_USER else False,
    )


def scope_of(install_dir, products) -> str:
    """The scope of the Windows Installer product *install_dir* belongs to,
    or ``""`` when none of *products* (:func:`win_msi.mixar_products`)
    is installed there."""
    from .app_paths import is_within

    for product in products or ():
        if product.get("location") and is_within(install_dir, product["location"]):
            return product.get("scope") or ""
    return ""


# ============================================================================
# What earlier attempts learned (per user)
# ============================================================================


def _config():
    from mixar.config.config import get_config

    return get_config()


def refused_version():
    """``(version, refusal)`` the installer refused here, or ``("", "")``."""
    try:
        value = _config().get(INSTALLER_REFUSED_CONFIG_KEY) or {}
        return str(value.get("version") or ""), str(value.get("refusal") or "")
    except Exception:  # noqa: BLE001 - a bad overlay value means nothing learned
        return "", ""


def remember_refusal(version, refusal) -> None:
    """The installer for *version* refused this copy: from now on that
    version is offered as a download, never installed by itself again."""
    from mixar.config.config import add_config

    refusal = refusal if refusal in MSI_REFUSALS else ""
    if version:
        add_config(INSTALLER_REFUSED_CONFIG_KEY, {"version": version, "refusal": refusal})


def _learned_block():
    """The stored 1625 lesson: ``{"disable_msi": <policy then>}`` or None.
    An earlier build stored ``True`` (policy then unknown)."""
    try:
        value = _config().get(USER_INSTALLS_BLOCKED_CONFIG_KEY)
    except Exception:  # noqa: BLE001
        return None
    if value is True:
        return {"disable_msi": None}
    return value if isinstance(value, dict) and value.get("blocked") else None


def learned_user_installs_blocked() -> bool:
    return _learned_block() is not None


def remember_user_installs_blocked(disable_msi=None) -> None:
    """msiexec answered 1625 without an administrator: ask from now on,
    remembering the ``DisableMSI`` policy it saw."""
    from mixar.config.config import add_config

    add_config(USER_INSTALLS_BLOCKED_CONFIG_KEY, {"blocked": True, "disable_msi": disable_msi})


def forget_user_installs_blocked() -> None:
    """Installs without an administrator work here (again)."""
    from mixar.config.config import add_config

    if _learned_block() is not None:
        add_config(USER_INSTALLS_BLOCKED_CONFIG_KEY, False)


def forget_when_policy_allows(disable_msi) -> bool:
    """IT set ``DisableMSI`` to 0 since the 1625 was learned: forget it.
    Returns True when it did. A 1625 that came with the policy already at 0
    (some other rule refused) stays learned, so this cannot loop."""
    learned = _learned_block()
    if learned is None or disable_msi != 0 or learned.get("disable_msi") == 0:
        return False
    forget_user_installs_blocked()
    logger.info("DisableMSI is 0 now: installing without the administrator prompt again")
    return True


# ============================================================================
# The move out of Program Files
# ============================================================================


def moved_from() -> str:
    """The folder the installed product moved Mixar out of, or ``""``: only
    an install that put Mixar somewhere else writes this HKCU value
    (WIX.template, ``MixarMovedFrom``), and the next upgrade removes it."""
    if os.name != "nt":
        return ""
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, MIXAR_REGISTRY_KEY) as key:
            value = winreg.QueryValueEx(key, MOVED_FROM_VALUE)[0]
    except OSError:
        return ""
    return value if isinstance(value, str) else ""


def program_files_dirs() -> list:
    """Where every release before #2079 installed for a normal user."""
    roots = [os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles"),
             os.environ.get("ProgramFiles(x86)")]
    return [root for root in roots if root] or [r"C:\Program Files"]


def is_program_files(path) -> bool:
    from .app_paths import is_within

    return bool(path) and any(is_within(path, root) for root in program_files_dirs())


def moved_from_program_files() -> bool:
    """True while the installed product is the one that moved Mixar out of
    Program Files."""
    return is_program_files(moved_from())
