# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Named secrets in the OS credential store — and the ONE entry that holds
every Python-owned secret.

The same mechanism `auth/core/auth.py` uses for the Mixar tokens: the
"MixarSafeStorage" keyring service on macOS/Linux (Keychain / SecretService)
and the Windows Credential Manager helpers (``<name>@MixarSafeStorage``
generic credentials) on Windows. ``get_secret / set_secret / delete_secret``
is the raw per-entry surface.

**Why one entry.** On macOS every Keychain item carries its own access list,
so an app whose code-signing identity changed (every ad-hoc dev rebuild, and
until the bundle id lost its version stamp, every minor release) is asked
"Mixar wants to access…" once PER ITEM. Everything Python owns therefore
lives in a single JSON bundle under one entry (`BUNDLE_ENTRY`): the BYOK
record of every Mixar account on this machine and the auth module's
refresh-attempt marker. One item, one approval at most. The two login tokens
stay in their own items because the C++ shell reads them before Python runs
(`creator_auth.cc`, which already suppresses the prompt and self-heals a
stale item). The bundle is read ONCE per process and cached (`get_value`),
so the store is not touched per agent message; a read the store refused
(locked keychain, unexpected status) is remembered for `BUNDLE_RETRY_S` and
then tried again, so a locked keychain is not hammered per message but is
picked up once unlocked — never latched for the process, since the
refresh-attempt marker in here gates every token refresh.

Windows caps a generic credential blob at ``CRED_MAX_CREDENTIAL_BLOB_SIZE``
(2560 bytes). A Codex access token alone can exceed that, so values longer
than one chunk are split across ``<name>#1 … <name>#n`` entries behind a
marker in the head entry (`credential_store_win`). macOS and SecretService
take the whole value.

Every function here BLOCKS on the OS store (Keychain can take tens of
milliseconds and may prompt) — call them from a worker thread, never from a
draw callback or the composer's main-thread send path.
"""

from __future__ import annotations

import json
import platform
import threading
import time
from typing import Any, Dict, Optional

from mixar.config.logging_config import get_logger

from . import credential_store_win as _win

logger = get_logger(__name__)

SERVICE_NAME = "MixarSafeStorage"

_IS_WINDOWS = platform.system() == "Windows"
_IS_MACOS = platform.system() == "Darwin"


# Names whose item another signing identity owns (macOS): read as absent for
# the rest of the session, warned about once, never retried per request.
_foreign: set = set()
# Values that could not be written because a foreign item holds the name:
# served from memory for this session, so the app still works (dev rebuilds
# without MIXAR_DEV_SIGN_ID); the user signs in again next launch.
_volatile: Dict[str, str] = {}
_memo_lock = threading.RLock()

_FOREIGN_REMEDY = (
    "Keychain item %r belongs to another build of Mixar and cannot be read or replaced "
    "without a dialog; kept in memory for this session only. To fix it for good: "
    "set MIXAR_DEV_SIGN_ID for dev builds, or run  security delete-generic-password "
    "-s MixarSafeStorage -a %r"
)


def _read_secret(name: str) -> Optional[str]:
    """The stored value or None when absent; raises when the store refused."""
    with _memo_lock:
        if name in _volatile:
            return _volatile[name]
        if name in _foreign:
            return None
    if _IS_WINDOWS:
        return _win.get(name)
    if _IS_MACOS:
        return _mac_read_quiet(name)
    import keyring

    value = keyring.get_password(SERVICE_NAME, name)
    return value or None


def _mark_foreign(name: str) -> None:
    with _memo_lock:
        if name in _foreign:
            return
        _foreign.add(name)
    logger.warning(_FOREIGN_REMEDY, name, name)


# ---------------------------------------------------------------------------
# macOS: read without the SecurityAgent dialog; a stale item is dropped
# ---------------------------------------------------------------------------
#
# A Keychain item is bound to the signing identity of the app that created it.
# Read by a different identity (an earlier build, before the bundle id lost
# its version stamp), the default is a "Mixar wants to access…" dialog whose
# "Allow" grants ONE read — and the app reads tokens on every request, so a
# user saw the dialog dozens of times until they found "Always Allow". The C++
# shell already reads with `kSecUseAuthenticationUIFail` and drops a stale
# item (`creator_auth.cc`); this is the same rule for every item Python reads:
# never a dialog — a stale token means signing in again, a stale bundle means
# entering the key again, both once, since the identity is now stable.
# A LOCKED keychain also answers "interaction not allowed", so the lock state
# is checked first and a locked store raises instead of deleting anything.

_SEC_ITEM_NOT_FOUND = -25300
_SEC_AUTH_FAILED = -25293
_SEC_DUPLICATE_ITEM = -25299
_SEC_INTERACTION_NOT_ALLOWED = -25308
_SEC_UNLOCK_STATE = 1   # kSecUnlockStateStatus bit of SecKeychainGetStatus


class KeychainLocked(RuntimeError):
    """The login keychain is locked: nothing can be read without a dialog."""


def _mac_keychain_locked() -> bool:
    import ctypes
    from ctypes import byref, c_uint32, c_void_p

    from keyring.backends.macOS import api

    get_status = api._sec.SecKeychainGetStatus
    get_status.restype = api.OS_status
    get_status.argtypes = (c_void_p, ctypes.POINTER(c_uint32))
    status = c_uint32(0)
    if get_status(None, byref(status)) != 0:
        return False   # cannot tell: let the read itself decide
    return not (status.value & _SEC_UNLOCK_STATE)


class _no_keychain_dialogs:
    """Context: SecurityAgent dialogs are refused for this process while
    inside — an operation that would have prompted fails with
    errSecInteractionNotAllowed instead. ``kSecUseAuthenticationUI`` only
    governs the data-protection keychain; for the login keychain this
    process-wide switch (`SecKeychainSetUserInteractionAllowed`) is the one
    that works, verified against an item created by another binary."""

    def __enter__(self):
        import ctypes

        from keyring.backends.macOS import api

        self._set = api._sec.SecKeychainSetUserInteractionAllowed
        self._set.restype = api.OS_status
        self._set.argtypes = (ctypes.c_ubyte,)
        self._set(0)
        return self

    def __exit__(self, *exc):
        self._set(1)
        return False


def _mac_copy_quiet(name: str) -> tuple:
    """``(status, value)`` of a SecItemCopyMatching that never prompts."""
    from ctypes import byref, c_void_p

    from keyring.backends.macOS import api

    query = api.create_query(
        kSecClass=api.k_("kSecClassGenericPassword"),
        kSecMatchLimit=api.k_("kSecMatchLimitOne"),
        kSecAttrService=SERVICE_NAME,
        kSecAttrAccount=name,
        kSecReturnData=api.create_cfbool(True),
    )
    data = c_void_p()
    with _no_keychain_dialogs():
        status = api.SecItemCopyMatching(query, byref(data))
    if status != 0:
        return status, None
    return 0, api.cfstr_to_str(data)


def _mac_delete_quiet(name: str) -> int:
    """Delete without a dialog; the status (an item owned by another signing
    identity answers errSecInvalidOwnerEdit and stays)."""
    from keyring.backends.macOS import api

    query = api.create_query(
        kSecClass=api.k_("kSecClassGenericPassword"),
        kSecAttrService=SERVICE_NAME,
        kSecAttrAccount=name,
    )
    with _no_keychain_dialogs():
        return api.SecItemDelete(query)


def _mac_add(name: str, value: str) -> int:
    from keyring.backends.macOS import api

    query = api.create_query(
        kSecClass=api.k_("kSecClassGenericPassword"),
        kSecAttrService=SERVICE_NAME,
        kSecAttrAccount=name,
        kSecValueData=value,
    )
    with _no_keychain_dialogs():
        return api.SecItemAdd(query, None)


def _mac_set(name: str, value: str, *, delete_quiet=None, add=None) -> bool:
    """Replace ``name`` without a dialog.

    Our own item is replaced silently. An item under this name that another
    signing identity owns can be neither read nor deleted — macOS offers a
    dialog for reading, never for deleting another app's item
    (errSecInvalidOwnerEdit) — so SecItemAdd answers errSecDuplicateItem.
    That cannot happen to a shipped build (the names arrived with the
    stable identity) but does on an ad-hoc dev rebuild without
    `MIXAR_DEV_SIGN_ID`. The value is then kept in process memory for this
    session (`_volatile`) so the app works, with the remedy logged once.
    The callables are injectable for tests.
    """
    delete_quiet = delete_quiet or _mac_delete_quiet
    add = add or _mac_add
    with _memo_lock:
        if name in _foreign:
            _volatile[name] = value
            return True
    delete_quiet(name)
    status = add(name, value)
    if status == _SEC_DUPLICATE_ITEM:
        _mark_foreign(name)
        with _memo_lock:
            _volatile[name] = value
        return True
    if status != 0:
        logger.warning("Credential store write failed for %s: %s", name, status)
        return False
    return True


def _mac_read_quiet(name: str, *, copy=None, locked=None, delete=None) -> Optional[str]:
    """Read ``name`` without ever raising the SecurityAgent dialog.

    Absent → None. Bound to another signing identity → the item is deleted
    and None is returned (the owner re-enters it once). Locked keychain →
    `KeychainLocked` (nothing deleted; the caller remembers the failure).
    The three callables are injectable for tests.
    """
    copy = copy or _mac_copy_quiet
    locked = locked or _mac_keychain_locked
    delete = delete or _mac_delete_quiet
    status, value = copy(name)
    if status == 0:
        return value or None
    if status == _SEC_ITEM_NOT_FOUND:
        return None
    if status in (_SEC_INTERACTION_NOT_ALLOWED, _SEC_AUTH_FAILED):
        if locked():
            raise KeychainLocked(name)
        # Ours by name, another signing identity's by access list. The
        # keychain's partition check is per TEAM for an Apple-issued
        # certificate (stable across releases) but per BUILD HASH for an
        # ad-hoc or self-signed dev build, so on a dev machine every rebuild
        # lands here. Delete succeeds when the certificate still matches
        # (the item is dropped: the user signs in / enters the key once,
        # no dialog); a foreign one answers errSecInvalidOwnerEdit and is
        # left alone for the session.
        if delete(name) == 0:
            logger.warning(
                "Credential store: %s was created by another build of Mixar; dropped (no dialog). "
                "A dev rebuild changes the keychain identity unless signed with an Apple-issued "
                "certificate; sign in / enter the key again.", name)
        else:
            _mark_foreign(name)
        return None
    raise RuntimeError(f"SecItemCopyMatching failed for {name}: {status}")


def get_secret(name: str) -> Optional[str]:
    """The stored value, or None when absent or unreadable."""
    try:
        return _read_secret(name)
    except Exception as exc:  # noqa: BLE001 — a locked store reads as absent
        logger.debug("Credential store read failed for %s: %s", name, type(exc).__name__)
        return None


def set_secret(name: str, value: str) -> bool:
    """Store (replace) ``value`` under ``name``. Returns False on failure."""
    try:
        if _IS_WINDOWS:
            return _win.set_(name, value)
        if _IS_MACOS:
            return _mac_set(name, value)
        import keyring

        keyring.set_password(SERVICE_NAME, name, value)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Credential store write failed for %s: %s", name, type(exc).__name__)
        return False


def delete_secret(name: str) -> bool:
    """Remove ``name``. Absent counts as success."""
    try:
        if _IS_WINDOWS:
            return _win.delete(name)
        if _IS_MACOS:
            with _memo_lock:
                _volatile.pop(name, None)
                if name in _foreign:
                    return True          # not ours to delete; nothing of ours remains
            status = _mac_delete_quiet(name)
            return status in (0, _SEC_ITEM_NOT_FOUND)
        import keyring

        try:
            keyring.delete_password(SERVICE_NAME, name)
        except keyring.errors.PasswordDeleteError:
            return True  # nothing stored
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Credential store delete failed for %s: %s", name, type(exc).__name__)
        return False


# ---------------------------------------------------------------------------
# The bundle: one entry, every Python-owned secret, read once per process
# ---------------------------------------------------------------------------

BUNDLE_ENTRY = "Mixar.Secrets"
_BUNDLE_VERSION = 1

# A refused read is remembered this long before the store is asked again:
# long enough not to hammer a locked keychain per message, short enough that
# an unlocked keychain (or a transient fault) is picked up without a restart.
BUNDLE_RETRY_S = 30.0

_bundle_lock = threading.RLock()
_bundle: Optional[Dict[str, Any]] = None      # parsed `{"v", "values": {key: value}}`
_bundle_failed_at: Optional[float] = None     # monotonic time of the refused read
_clock = time.monotonic                       # injectable for tests


def _load_bundle() -> Optional[Dict[str, Any]]:
    """The parsed bundle (created empty when the entry is absent), cached
    for the process; None while the store cannot be read (retried after
    `BUNDLE_RETRY_S`)."""
    global _bundle, _bundle_failed_at
    with _bundle_lock:
        if _bundle is not None:
            return _bundle
        if _bundle_failed_at is not None and _clock() - _bundle_failed_at < BUNDLE_RETRY_S:
            return None
        try:
            raw = _read_secret(BUNDLE_ENTRY)
        except Exception as exc:  # noqa: BLE001 — locked / denied: back off, do not retry per message
            logger.warning("Credential store unavailable: %s", type(exc).__name__)
            _bundle_failed_at = _clock()
            return None
        _bundle_failed_at = None
        values: Dict[str, Any] = {}
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict) and isinstance(parsed.get("values"), dict):
                    values = parsed["values"]
                else:
                    logger.warning("Credential bundle unreadable; starting empty")
            except ValueError:
                logger.warning("Credential bundle is not JSON; starting empty")
        _bundle = {"v": _BUNDLE_VERSION, "values": values}
        return _bundle


def _save_bundle() -> bool:
    global _bundle, _bundle_failed_at
    with _bundle_lock:
        if _bundle is None:
            return False
        ok = set_secret(BUNDLE_ENTRY, json.dumps(_bundle, separators=(",", ":")))
        if not ok:
            # Unknown on-store state: forget the cache so the next read tells the truth.
            _bundle = None
            _bundle_failed_at = None
        return ok


def store_available() -> bool:
    """False while the store refused the last read (for `BUNDLE_RETRY_S`,
    or until a write or `invalidate_cache`)."""
    return _load_bundle() is not None


def get_value(key: str) -> Any:
    """The JSON value stored under ``key`` in the bundle, or None (absent, or
    the store cannot be read)."""
    bundle = _load_bundle()
    if bundle is None:
        return None
    with _bundle_lock:
        value = bundle["values"].get(key)
    return json.loads(json.dumps(value)) if value is not None else None   # a copy


def set_value(key: str, value: Any) -> bool:
    """Write ``value`` (JSON-serialisable) under ``key``; write-through."""
    global _bundle_failed_at
    with _bundle_lock:
        _bundle_failed_at = None              # a write is a fresh attempt
        bundle = _load_bundle()
        if bundle is None:
            return False
        bundle["values"][key] = json.loads(json.dumps(value))
        return _save_bundle()


def delete_value(key: str) -> bool:
    """Remove ``key``; absent counts as success."""
    global _bundle_failed_at
    with _bundle_lock:
        _bundle_failed_at = None
        bundle = _load_bundle()
        if bundle is None:
            return False
        if key not in bundle["values"]:
            return True
        del bundle["values"][key]
        return _save_bundle()


def invalidate_cache() -> None:
    """Forget the cached bundle (and a remembered failure): the next access
    reads the store again. Logout calls this (`key_store.forget_user`)."""
    global _bundle, _bundle_failed_at
    with _bundle_lock:
        _bundle = None
        _bundle_failed_at = None
    with _memo_lock:
        _foreign.clear()
        _volatile.clear()


def migrate_legacy_entry(legacy_name: str, key: str, parse=None) -> bool:
    """Move a value that an earlier build stored as its own entry
    (``legacy_name``) into the bundle under ``key`` and delete the old entry.
    ``parse`` turns the raw string into the stored value (default: as is).
    True when something was moved."""
    if get_value(key) is not None:
        return False
    raw = get_secret(legacy_name)
    if not raw:
        return False
    try:
        value = parse(raw) if parse else raw
    except Exception:  # noqa: BLE001 — an unreadable legacy value is dropped
        delete_secret(legacy_name)
        return False
    if set_value(key, value):
        delete_secret(legacy_name)
        return True
    return False
