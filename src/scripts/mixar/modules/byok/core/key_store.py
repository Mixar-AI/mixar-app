# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The BYOK key on THIS machine.

The backend keeps provider/model metadata and a masked preview only; the key
material lives here, in the OS credential store (`common/utils/credential_store`
— inside the ONE bundle entry every Python-owned secret shares, so the
Keychain asks at most once, and read once per process), and is attached to
every agent turn by `turn_credentials`.

One JSON record per Mixar user, keyed ``byok:<user id>`` inside the bundle so
two accounts on one machine never share a key (an earlier build's own
``BYOK:<user id>`` entry is moved into the bundle on first use):

    {"v": 2, "provider": "anthropic", "key": "<api key | bearer>"}
    {"v": 2, "provider": "codex", "key": None, "auth_path": "<auth.json path>",
     "expired_fingerprint": "<digest of the revoked refresh token> | None"}

``key`` is None for a keyless LOCAL endpoint (the record still exists, which
is how "a key is configured on this device" is answered). A Codex record
holds NO tokens: it points at the Codex CLI's own sign-in file (empty =
the default location), which `materialize` reads at use time, so the CLI
and Mixar never hold diverging refresh tokens. ``expired_fingerprint``
remembers which sign-in the refresh endpoint revoked; a fresh
``codex login`` writes a different token and clears it by itself.

Written on a successful PUT /agent/byok, replaced on the next, deleted on
DELETE /agent/byok. NOT deleted on Mixar logout — it is the user's own key on
their own machine. Every function may block on the credential store (the
first read of the process, every write): worker threads only.
"""

from __future__ import annotations

import base64
import json
import threading
from typing import Any, Callable, Dict, Optional

from mixar.config.logging_config import get_logger
from mixar.modules.common.utils import credential_store

from ..constants import BYOK_KEY_STORE_PREFIX, CODEX_PROVIDER_ID, LOCAL_PROVIDER_ID
from . import codex_auth
from mixar.modules.auth.core.auth import user_id_from_token  # noqa: F401 — the key record's scope

logger = get_logger(__name__)

_RECORD_VERSION = 2

_lock = threading.Lock()
# (token, user id) of the last derivation: the id is re-derived whenever the
# access token changed, so an account switch that skipped Logout (a
# session-expired re-login, a token pair adopted from another process) never
# reads or writes the previous account's record.
_user_memo: tuple = ("", None)


# ---------------------------------------------------------------------------
# User scope
# ---------------------------------------------------------------------------

def current_user_id() -> Optional[str]:
    """The signed-in Mixar user's id: the ``sub`` of the access token in the
    credential store, read on every call (dialog-free, milliseconds) so the
    scope always follows the token that is actually signed in. Blocking."""
    global _user_memo
    try:
        from mixar.modules.auth.core.auth import get_access_token

        token = get_access_token() or ""
    except Exception as exc:  # noqa: BLE001
        logger.debug("BYOK key store: user id unavailable: %s", type(exc).__name__)
        return None
    if not token:
        return None
    with _lock:
        memo_token, memo_id = _user_memo
        if memo_token == token:
            return memo_id
    user_id = user_id_from_token(token)
    with _lock:
        _user_memo = (token, user_id)
    return user_id


def forget_user() -> None:
    """Logout: drop the cached scope (the stored key itself stays) and the
    process's cached bundle, so the next sign-in reads the store afresh."""
    global _user_memo
    with _lock:
        _user_memo = ("", None)
    credential_store.invalidate_cache()


def _entry_name(user_id: str) -> str:
    """The key inside the credential bundle."""
    return f"{BYOK_KEY_STORE_PREFIX.lower()}:{user_id}"


def _legacy_entry_name(user_id: str) -> str:
    """The standalone entry an earlier build wrote (one Keychain item of its own)."""
    return f"{BYOK_KEY_STORE_PREFIX}:{user_id}"


# ---------------------------------------------------------------------------
# Record CRUD (blocking)
# ---------------------------------------------------------------------------

def make_record(
    provider: str,
    key: Optional[str],
    auth_path: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """A cloud/local record carries the key; a Codex record carries only the
    sign-in file reference (``auth_path``; "" = the CLI's default). ``model``
    is the model the key was saved on: it is what the dialog's "Use my key"
    re-sends when it resumes a paused key (`byok_client.resave_stored_key`),
    since the server keeps nothing once the key is paused. A record without
    it (an earlier build) can only be resumed through the settings dialog."""
    if provider == CODEX_PROVIDER_ID:
        return {
            "v": _RECORD_VERSION,
            "provider": provider,
            "key": None,
            "auth_path": (auth_path or "").strip(),
            "expired_fingerprint": None,
            "model": (model or "").strip(),
        }
    return {
        "v": _RECORD_VERSION,
        "provider": provider or "",
        "key": key or None,
        "model": (model or "").strip(),
    }


def materialize(record: Optional[Dict[str, Any]]) -> tuple:
    """``(record_for_this_turn, problem)``: a Codex record is completed from
    the sign-in file — ``key`` (access token), ``refresh_token``,
    ``account_id``, ``expired`` (the file's refresh token is the one the
    endpoint revoked), ``can_persist`` (the file can take a renewal back,
    checked before a refresh grant is spent) — in a COPY that is never
    written back to the store.
    ``problem`` is the user-safe message when the file cannot serve the turn
    (missing, unreadable, incomplete). Other records pass through."""
    if not record or record.get("provider") != CODEX_PROVIDER_ID:
        return record, None
    try:
        creds = codex_auth.read_auth_file(record.get("auth_path"))
    except codex_auth.CodexBundleError as exc:
        return None, exc.message
    fp = record.get("expired_fingerprint")
    live = dict(record)
    live.update(
        key=creds.access_token,
        refresh_token=creds.refresh_token,
        account_id=creds.account_id,
        expired=bool(fp) and fp == codex_auth.fingerprint(creds.refresh_token),
        can_persist=codex_auth.can_write_back(record.get("auth_path")),
    )
    return live, None


def persist_changes(record: Dict[str, Any], changes: Dict[str, Any], user_id: Optional[str] = None) -> bool:
    """Apply what a turn learned. Codex: renewed tokens go INTO the CLI's
    file (`codex_auth.write_back`), never into the store; ``expired``
    becomes the revoked token's fingerprint (or clears it). Other providers
    merge into the stored record."""
    if record.get("provider") != CODEX_PROVIDER_ID:
        return update(changes, user_id)
    ok = True
    if changes.get("key"):
        ok = codex_auth.write_back(record.get("auth_path"), changes["key"], changes.get("refresh_token"))
    if "expired" in changes:
        fp = codex_auth.fingerprint(record.get("refresh_token")) if changes["expired"] else None
        ok = update({"expired_fingerprint": fp}, user_id) and ok
    return ok


def load(user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """This device's record for the user, or None."""
    user_id = user_id or current_user_id()
    if not user_id:
        return None
    key = _entry_name(user_id)
    record = credential_store.get_value(key)
    if record is None:
        credential_store.migrate_legacy_entry(_legacy_entry_name(user_id), key, parse=json.loads)
        record = credential_store.get_value(key)
    if not isinstance(record, dict) or not record.get("provider"):
        return None
    if record.get("v", 1) < _RECORD_VERSION:
        # A v1 Codex record copied the tokens: drop them, point at the CLI's
        # file instead (the sign-in it was copied from) — and persist the
        # upgrade at once, so the token copy does not linger in the store.
        if record.get("provider") == CODEX_PROVIDER_ID:
            record = make_record(CODEX_PROVIDER_ID, None)
        else:
            record = make_record(record["provider"], record.get("key"))
        save(record, user_id)
    return record


def save(record: Dict[str, Any], user_id: Optional[str] = None) -> bool:
    user_id = user_id or current_user_id()
    if not user_id:
        logger.warning("BYOK key store: no signed-in user; key not stored on this device")
        return False
    return credential_store.set_value(_entry_name(user_id), record)


def delete(user_id: Optional[str] = None) -> bool:
    user_id = user_id or current_user_id()
    if not user_id:
        return False
    credential_store.delete_secret(_legacy_entry_name(user_id))
    return credential_store.delete_value(_entry_name(user_id))


def reassign(old_user_id: Optional[str], new_user_id: Optional[str]) -> bool:
    """Re-scope this device's record from one user to another: a guest's key
    becomes the account's when signing in claims the guest (the backend moved
    the row). The account's own record, if any, wins — then the guest's is
    simply dropped. True when a record now serves ``new_user_id``."""
    if not old_user_id or not new_user_id or old_user_id == new_user_id:
        return False
    record = load(old_user_id)
    if record is None:
        return False
    if load(new_user_id) is None and not save(record, new_user_id):
        return False
    delete(old_user_id)
    logger.info("BYOK key record re-scoped from the claimed guest to the account")
    return True


def update(changes: Dict[str, Any], user_id: Optional[str] = None) -> bool:
    """Merge ``changes`` into the stored record."""
    user_id = user_id or current_user_id()
    record = load(user_id)
    if record is None:
        return False
    record.update(changes)
    return save(record, user_id)


# ---------------------------------------------------------------------------
# Presence check for the UI (worker thread → main-thread callback)
# ---------------------------------------------------------------------------

def resumable_summary(record: Optional[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    """``{"provider", "model"}`` when ``record`` can be re-sent to the server
    without the user typing anything (a key-tab pick after a Mixie
    paused the key), else None. Pure apart from a Codex record, whose
    sign-in file is read (never copied): a file that is gone or whose
    sign-in the endpoint revoked cannot be resumed, only entered again.
    Local is never resumable here — its endpoint lives in the local-models
    manifest, not in this record — and neither is a record saved by a build
    that did not remember the model. Blocking (Codex): worker threads only."""
    if not record:
        return None
    provider = record.get("provider") or ""
    model = (record.get("model") or "").strip()
    if not provider or not model or provider == LOCAL_PROVIDER_ID:
        return None
    if provider == CODEX_PROVIDER_ID:
        live, problem = materialize(record)
        if problem is not None or (live or {}).get("expired"):
            return None
    elif not record.get("key"):
        return None
    return {"provider": provider, "model": model}


def check_resumable_async(on_done: Callable[[Optional[Dict[str, str]]], None]) -> None:
    """Calls ``on_done(summary)`` on the main thread with
    `resumable_summary` of this device's record (None when nothing here can
    be resumed)."""
    def _thread():
        summary = None
        try:
            summary = resumable_summary(load())
        except Exception as exc:  # noqa: BLE001
            logger.debug("BYOK resumable check failed: %s", type(exc).__name__)
        from .byok_client import schedule_on_main

        schedule_on_main(on_done, summary)

    threading.Thread(target=_thread, daemon=True, name="MixarBYOKResumable").start()


def check_presence_async(provider: str, on_done: Callable[[bool], None]) -> None:
    """Calls ``on_done(missing)`` on the main thread: True when this device
    holds no usable record for ``provider`` (none stored, another provider's,
    a Codex sign-in file that is gone, or one the endpoint revoked)."""
    def _thread():
        missing = True
        try:
            record = load()
            if record is not None and (record.get("provider") or "") == (provider or ""):
                live, problem = materialize(record)
                missing = problem is not None or bool((live or {}).get("expired"))
        except Exception as exc:  # noqa: BLE001
            logger.debug("BYOK key presence check failed: %s", type(exc).__name__)
        from .byok_client import schedule_on_main

        schedule_on_main(on_done, missing)

    threading.Thread(target=_thread, daemon=True, name="MixarBYOKKeyPresence").start()
