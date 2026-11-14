# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Attach the user's key to an agent turn.

The backend no longer holds BYOK key material, so every ``chat`` / ``input``
command carries it (`byok_key`, plus `byok_account_id` for Codex). The
composer's send path runs on Blender's main thread and the key lives in the
OS credential store, so the lookup — and a Codex token refresh when the
access token is within a day of expiry — happens on a worker thread; the
command is dispatched from the main-thread callback (`turn_transport._send`).

`resolve` is the pure decision table (tested without bpy or the network):

    record            → fields                              / refusal
    none              → {}  (the server decides: 409 when it needs a key)
    other provider's  → {}  (another device switched the account; the
                            server's 409 drives "key needed on this device")
    cloud / local     → {byok_key} (omitted for a keyless local endpoint)
    codex (tokens read from the CLI's auth.json by `key_store.materialize`)
      file gone       → refuse (run codex login), device marked missing
      fresh           → {byok_key, byok_account_id}
      stale           → refresh first; renewed tokens are written back
                        INTO auth.json (`key_store.persist_changes`); a
                        file that cannot take them (not writable) is never
                        refreshed — the grant rotates the refresh token and
                        losing it would sign the Codex CLI out too
      changed during  → (`serve`) the file vanished, became unwritable or
      the refresh       was replaced by a newer `codex login`, or this
                        device now names another file: the renewal is not
                        used; the turn is resolved once more from the
                        sign-in as it is now (refused when it cannot serve).
                        A refresh token is never spent twice: a file still
                        holding the spent one refuses as not writable
      refresh revoked → refuse (sign-in expired); that sign-in is remembered
                        by fingerprint until `codex login` replaces it
      refresh network → current token if still valid, else refuse (retryable)

`prepare` adds two rules around it: an `input` abort is sent at once with no
fields (the server exempts it — a dead Codex sign-in must never keep the user
from declining a plan), and the key field is SEALED to the backend's X25519
transport key before it leaves the worker thread (`sealed` →
`transport_seal`; the backend refuses plaintext, and a key that cannot be
sealed refuses the turn rather than falling back). Before the first
credential fetch has landed the mirror reads "inactive" and the turn goes
out keyless, synchronously, like every platform turn; a 409 in that window
refreshes the mirror instead of flipping "Key needed on this device"
(`byok_notice`).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from mixar.config.logging_config import get_logger

from ..constants import (
    BYOK_CODEX_EXPIRED_CODE,
    BYOK_CODEX_REFRESH_FAILED_CODE,
    BYOK_TURN_ABORT_ACTION,
    BYOK_TURN_ACCOUNT_FIELD,
    BYOK_TURN_KEY_FIELD,
    CODEX_PROVIDER_ID,
)
from . import codex_auth, credential_state, key_store

logger = get_logger(__name__)

Refresher = Callable[[str], codex_auth.RefreshOutcome]


@dataclass
class Resolution:
    fields: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None       # user-safe refusal; the turn is NOT sent
    code: Optional[str] = None        # BYOK_CODEX_* code for the error path
    record_changes: Optional[Dict[str, Any]] = None  # persisted by `prepare`
    key_missing: bool = False         # the record cannot serve the account's provider

    @property
    def blocked(self) -> bool:
        return self.error is not None


def resolve(record: Optional[dict], now: Optional[float] = None,
            refresher: Optional[Refresher] = None, *,
            active_provider: Optional[str] = None) -> Resolution:
    """The payload fields for this turn, or a refusal. Pure.

    ``active_provider`` is the account's provider as the server reports it
    (None when not known yet): a record for another provider is NOT sent.
    The server pairs the account's row with whatever key arrives, so a key
    for the old provider would pass the credit bypass and die on a provider
    401 mid-turn instead of the clean 409 that marks this device.
    """
    if not record:
        return Resolution()
    provider = record.get("provider") or ""
    if active_provider and provider != active_provider:
        return Resolution(key_missing=True)
    key = record.get("key") or None
    if provider != CODEX_PROVIDER_ID:
        return Resolution({BYOK_TURN_KEY_FIELD: key} if key else {})
    return _resolve_codex(record, key, now, refresher)


def _codex_fields(token: str, account_id: Optional[str]) -> Dict[str, Any]:
    fields = {BYOK_TURN_KEY_FIELD: token}
    if account_id:
        fields[BYOK_TURN_ACCOUNT_FIELD] = account_id
    return fields


def _resolve_codex(record: dict, token: Optional[str], now: Optional[float],
                   refresher: Optional[Refresher]) -> Resolution:
    account_id = record.get("account_id") or None
    if record.get("expired") or not token:
        return Resolution(error=codex_auth.MSG_SIGN_IN_EXPIRED, code=BYOK_CODEX_EXPIRED_CODE)
    if not codex_auth.needs_refresh(token, now):
        return Resolution(_codex_fields(token, account_id))

    refresh_token = record.get("refresh_token") or None
    still_valid = not codex_auth.is_expired(token, now)
    if not refresh_token or refresher is None:
        if still_valid:
            return Resolution(_codex_fields(token, account_id))
        return Resolution(error=codex_auth.MSG_SIGN_IN_EXPIRED, code=BYOK_CODEX_EXPIRED_CODE)
    if record.get("can_persist") is False:
        if still_valid:
            return Resolution(_codex_fields(token, account_id))
        return Resolution(error=codex_auth.MSG_FILE_NOT_WRITABLE, code=BYOK_CODEX_REFRESH_FAILED_CODE)

    outcome = refresher(refresh_token)
    if outcome.status == "ok" and outcome.access_token:
        changes = {"key": outcome.access_token, "expired": False}
        if outcome.refresh_token:
            changes["refresh_token"] = outcome.refresh_token
        return Resolution(_codex_fields(outcome.access_token, account_id), record_changes=changes)
    if outcome.status == "revoked":
        return Resolution(
            error=codex_auth.MSG_SIGN_IN_EXPIRED, code=BYOK_CODEX_EXPIRED_CODE,
            record_changes={"expired": True},
        )
    # Network / transient: the sign-in is not known to be gone.
    if still_valid:
        return Resolution(_codex_fields(token, account_id))
    return Resolution(
        error=outcome.message or codex_auth.MSG_REFRESH_UNREACHABLE,
        code=BYOK_CODEX_REFRESH_FAILED_CODE,
    )


def serve(record: Optional[dict], *, active_provider: Optional[str] = None,
          user_id: Optional[str] = None) -> Resolution:
    """`resolve` this device's ``record`` for a request and persist what it
    learned. Blocking (file reads, a Codex refresh): worker threads only.

    A Codex renewal serves the request only when it reached the sign-in it
    renewed: the write-back landed (the file is still there, writable and not
    replaced by a newer ``codex login`` meanwhile) and this device's record
    still names that file. Otherwise the renewed token belongs to a sign-in
    that is gone or superseded, so the request is resolved once more from
    the record and file as they are NOW — never sent with the stale token.

    A refresh token is spent at most once per request: a file that still
    holds the token a renewal just spent could not take the renewal (a
    permissions change, a full disk, a lock), and refreshing it again would
    only be refused as a reuse. That refuses with the not-writable message
    while the cause is still in front of the user — the CLI's own sign-in
    now holds a spent token too — rather than sending this turn and failing
    the next as "sign-in expired"."""
    spent = set()
    for _attempt in range(_SERVE_PASSES):
        live, refusal = _current(record, spent)
        if refusal is not None:
            return refusal
        resolution = resolve(live, refresher=codex_auth.refresh_access_token,
                             active_provider=active_provider)
        changes = resolution.record_changes
        if not changes:
            return resolution
        persisted = key_store.persist_changes(live, changes, user_id)
        if not changes.get("key") or live.get("provider") != CODEX_PROVIDER_ID:
            return resolution
        record = key_store.load(user_id)
        if persisted and (record or {}).get("auth_path") == live.get("auth_path"):
            return resolution
        spent.add(live.get("refresh_token"))
        logger.warning("BYOK Codex sign-in changed during its renewal; resolving it again")
    # The sign-in changed under every renewal: serve it as it is now and
    # renew no further (a fresh or still-valid token goes out, an expired
    # one refuses as expired).
    live, refusal = _current(record, spent)
    if refusal is not None:
        return refusal
    return resolve(live, active_provider=active_provider)


_SERVE_PASSES = 2


def _current(record, spent):
    """``(live, refusal)`` for the record and sign-in file as they are now."""
    live, problem = key_store.materialize(record)
    if problem is not None:
        # The Codex sign-in file cannot serve the turn (codex logout,
        # never logged in): refuse like an expired sign-in.
        return None, Resolution(error=problem, code=BYOK_CODEX_EXPIRED_CODE)
    if live and live.get("refresh_token") in spent:
        return None, Resolution(error=codex_auth.MSG_FILE_NOT_WRITABLE,
                                code=BYOK_CODEX_REFRESH_FAILED_CODE)
    return live, None


def sealed(resolution: Resolution) -> Resolution:
    """`resolution` with its key field sealed to the backend's transport key
    (`transport_seal`): the per-turn ``byok_key`` — a cloud key, a Local
    bearer, a Codex access token alike — never leaves this device in
    plaintext. ``byok_account_id`` is not a secret and stays as is. A key
    that cannot be sealed (no server key, network down) is a refusal of the
    turn, never a plaintext fallback. Worker thread only: HTTP on a miss.
    """
    if resolution.blocked or BYOK_TURN_KEY_FIELD not in resolution.fields:
        return resolution
    from . import transport_seal

    try:
        envelope = transport_seal.seal(resolution.fields[BYOK_TURN_KEY_FIELD])
    except transport_seal.SealError as exc:
        return Resolution(error=exc.message, code=exc.code, key_missing=resolution.key_missing)
    fields = dict(resolution.fields)
    fields[BYOK_TURN_KEY_FIELD] = envelope
    return Resolution(fields, record_changes=resolution.record_changes,
                      key_missing=resolution.key_missing)


# ---------------------------------------------------------------------------
# Main-thread entry point
# ---------------------------------------------------------------------------

def prepare(on_ready: Callable[[Dict[str, Any], Optional[Dict[str, str]]], None], *,
            method: str = "chat", action: Optional[str] = None) -> None:
    """Resolve the turn's BYOK fields, then ``on_ready(fields, error)`` on the
    main thread. ``error`` is ``{"message", "code"}`` when the turn must not
    be sent. Synchronous (and empty) while BYOK is inactive — including
    before the cold-start credential fetch has landed — so the plain
    platform path keeps its current timing, and for an ``input`` abort
    (``method`` / ``action`` are the command's), which the server accepts
    without a key and which must never wait on the store or a Codex refresh.
    """
    if method == "input" and action == BYOK_TURN_ABORT_ACTION:
        on_ready({}, None)
        return
    state = credential_state.snapshot()
    if not state.get("byok_is_active"):
        on_ready({}, None)
        return
    active_provider = state.get("byok_current_provider") or None

    def _thread():
        resolution = Resolution()
        record = None
        try:
            record = key_store.load()
            resolution = sealed(serve(record, active_provider=active_provider))
        except Exception as exc:  # noqa: BLE001 — never block the turn on a store fault
            logger.warning("BYOK turn credentials unavailable: %s", type(exc).__name__)
            resolution = Resolution()  # keyless, never plaintext: the server decides
        error = {"message": resolution.error, "code": resolution.code} if resolution.blocked else None
        missing = (record is None or resolution.key_missing
                   or resolution.code == BYOK_CODEX_EXPIRED_CODE)
        from .byok_client import schedule_on_main

        schedule_on_main(_deliver, on_ready, resolution.fields, error, missing)

    threading.Thread(target=_thread, daemon=True, name="MixarBYOKTurnKey").start()


def _deliver(on_ready, fields, error, missing: bool) -> None:
    credential_state.set_device_key_missing(missing)
    on_ready(fields, error)
