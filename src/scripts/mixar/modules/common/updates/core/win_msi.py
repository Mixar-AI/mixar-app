# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Windows Installer Queries

What Windows itself says about the Mixar installs this account can see,
and the facts about this machine and token that decide whether msiexec
may run without an administrator (#2079). ``msi.dll`` and ``advapi32``
through ctypes plus one ``winreg`` read: no subprocess, a few
milliseconds, safe on the UI thread.

The Uninstall key is not enough on its own: Windows writes a per-user
product's key under HKLM, and two accounts with the same version share
that one key, whose ``InstallLocation`` is whoever installed last. Windows
Installer answers for this account: its own per-user products and the
machine's.

Every function raises ``OSError`` (or returns None) when it cannot tell;
callers treat that as unknown, which elevates exactly as before.
"""

import ctypes
import os
import sys

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# MSIINSTALLCONTEXT_*: per-user managed (assigned by policy), per-user
# unmanaged (a normal per-user install), per-machine.
CONTEXT_USER_MANAGED = 1
CONTEXT_USER_UNMANAGED = 2
CONTEXT_MACHINE = 4
SCOPE_PER_USER = "per_user"
SCOPE_MACHINE = "machine"
_CONTEXT_SCOPES = (
    (CONTEXT_USER_UNMANAGED, SCOPE_PER_USER),
    (CONTEXT_USER_MANAGED, SCOPE_PER_USER),
    (CONTEXT_MACHINE, SCOPE_MACHINE),
)

_ERROR_SUCCESS = 0
_ERROR_MORE_DATA = 234
_ERROR_NO_MORE_ITEMS = 259
_MAX_PRODUCTS = 32

# GetTokenInformation(TokenElevationType): 1 default (a standard user, or an
# administrator with UAC off), 2 full (already elevated), 3 limited (an
# administrator's filtered token, which can elevate itself at a prompt).
_TOKEN_QUERY = 0x0008
_TOKEN_ELEVATION_TYPE = 18
_ELEVATION_FULL = 2
_ELEVATION_LIMITED = 3

_INSTALLER_POLICY_KEY = r"SOFTWARE\Policies\Microsoft\Windows\Installer"
_VER_NT_WORKSTATION = 1


def _msi():
    msi = ctypes.WinDLL("msi")
    enum = msi.MsiEnumRelatedProductsW
    enum.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_wchar_p]
    enum.restype = ctypes.c_uint32
    info = msi.MsiGetProductInfoExW
    info.argtypes = [
        ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_wchar_p,
        ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint32),
    ]
    info.restype = ctypes.c_uint32
    return msi


def _related_products(msi, upgrade_code) -> list:
    codes = []
    for index in range(_MAX_PRODUCTS):
        buffer = ctypes.create_unicode_buffer(39)
        status = msi.MsiEnumRelatedProductsW(upgrade_code, 0, index, buffer)
        if status == _ERROR_NO_MORE_ITEMS:
            break
        if status != _ERROR_SUCCESS:
            raise OSError(status, "MsiEnumRelatedProducts failed")
        codes.append(buffer.value)
    return codes


def _product_info(msi, code, context, prop):
    """*prop* of product *code* in *context* for this user; None when the
    product is not installed in that context."""
    size = ctypes.c_uint32(0)
    status = msi.MsiGetProductInfoExW(code, None, context, prop, None, ctypes.byref(size))
    if status not in (_ERROR_SUCCESS, _ERROR_MORE_DATA):
        return None
    size.value += 1
    buffer = ctypes.create_unicode_buffer(size.value)
    status = msi.MsiGetProductInfoExW(code, None, context, prop, buffer, ctypes.byref(size))
    return buffer.value if status == _ERROR_SUCCESS else None


def mixar_products(upgrade_code) -> list:
    """``[{"code", "scope", "location", "version"}]`` for every Mixar this
    account can see: its own per-user installs and the machine's.

    Raises ``OSError`` when Windows Installer cannot be asked.
    """
    msi = _msi()
    products = []
    for code in _related_products(msi, upgrade_code):
        for context, scope in _CONTEXT_SCOPES:
            version = _product_info(msi, code, context, "VersionString")
            if version is None:
                continue
            products.append({
                "code": code, "scope": scope, "version": version,
                "location": _product_info(msi, code, context, "InstallLocation") or "",
            })
    return products


def token_elevation_type():
    """This process token's TOKEN_ELEVATION_TYPE (1, 2 or 3), or None."""
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD)]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), _TOKEN_QUERY,
                                     ctypes.byref(token)):
        return None
    try:
        value, size = ctypes.c_int(0), wintypes.DWORD(0)
        if not advapi32.GetTokenInformation(token, _TOKEN_ELEVATION_TYPE, ctypes.byref(value),
                                            ctypes.sizeof(value), ctypes.byref(size)):
            return None
        return value.value
    finally:
        kernel32.CloseHandle(token)


def can_self_elevate() -> bool:
    """True when a UAC prompt would run msiexec as THIS account.

    A limited administrator token elevates itself; an elevated token, or an
    administrator with UAC off, already is. A standard user's prompt asks
    for another account's password, and msiexec then runs as that account,
    whose per-user install lands in its own profile: never offered.
    """
    try:
        kind = token_elevation_type()
        if kind in (_ELEVATION_FULL, _ELEVATION_LIMITED):
            return True
        return bool(kind is not None and ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        logger.debug("Could not read the token's elevation type", exc_info=True)
        return False


def disable_msi_value():
    """The ``DisableMSI`` policy as set (an int), or None when it is not."""
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _INSTALLER_POLICY_KEY, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            value = winreg.QueryValueEx(key, "DisableMSI")[0]
    except OSError:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def user_installs_blocked_by_policy() -> bool:
    """Does Windows Installer policy refuse installs without an administrator?

    ``DisableMSI`` 1 refuses non-administrator installs (exit 1625), 2 every
    install. Absent, Windows Server behaves as 1 and Windows 10/11 as 0.
    """
    value = disable_msi_value()
    if value is None:
        product_type = getattr(sys.getwindowsversion(), "product_type", _VER_NT_WORKSTATION)
        return product_type != _VER_NT_WORKSTATION
    return value != 0


def profile_dirs() -> list:
    """This user's folders a per-user install lives in (and may write)."""
    return [path for path in (os.environ.get("LOCALAPPDATA"), os.environ.get("USERPROFILE"))
            if path]
