# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Seal a BYOK key to the backend's X25519 key before it leaves this device.

The backend stores no key, but until now every key field (the per-turn
``byok_key``, the ``api_key`` of a credential save) was plaintext inside
TLS, which every TLS-terminating hop in front of the service could read.
Now the desktop seals it to a public key the backend serves, and the
backend refuses plaintext (``byok_key_unsealed``, 400).

Wire format (the backend's ``core/byok_transport.py`` is the reference and
``seal_with`` mirrors it byte for byte):

    mxs1.<kid>.<base64url, no padding: enc[32] || ciphertext>

RFC 9180 HPKE, base mode, single-shot (`hpke.py`, a copy of the backend's):
DHKEM(X25519, HKDF-SHA256), HKDF-SHA256, AES-128-GCM — the suite the RFC
publishes test vectors for, replayed on both ends. ``enc`` is the KEM
encapsulation (a fresh ephemeral X25519 key per envelope); the HPKE info is
`BYOK_TRANSPORT_HKDF_INFO`; the AEAD associated data is utf8(``kid``); the
nonce is the context's base nonce (seq 0) and is not transmitted.

The server key comes from ``GET /agent/byok/transport-key`` and is cached
in process memory for an hour (`BYOK_TRANSPORT_KEY_TTL_S`). A key sealed to a
``kid`` the server rotated out is ``byok_transport_key_stale`` (409): the
caller calls `invalidate` and resends that one command once. A fetch that
fails is a refusal of the turn / the save — the key is NEVER sent in
plaintext as a fallback — with a user-safe message: a 503
(``byok_transport_unavailable``) says Mixar cannot accept keys right now, a
network failure says check the connection. Nothing here is sealed unless a
key is about to be sent, so the platform-credit path never fetches.

`seal_with` is pure (no network, no state); `public_key` / `seal` make an
HTTP call on a miss and are worker-thread only. Nothing here logs a secret
or an envelope.
"""

from __future__ import annotations

import base64
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import n_

from ..constants import (
    BYOK_TRANSPORT_ALGORITHM,
    BYOK_TRANSPORT_ENVELOPE_PREFIX,
    BYOK_TRANSPORT_HKDF_INFO,
    BYOK_TRANSPORT_KEY_TTL_S,
    BYOK_TRANSPORT_UNAVAILABLE_CODE,
    BYOK_TRANSPORT_UNREACHABLE_CODE,
)

from . import hpke

logger = get_logger(__name__)

_KEY_LEN = hpke.N_PK

# User-facing messages (msgids; the UI translates).
MSG_TRANSPORT_UNAVAILABLE = n_(
    "Mixar cannot accept your key right now — try again in a moment."
)
MSG_TRANSPORT_UNREACHABLE = n_(
    "Could not fetch Mixar's key-sealing key — check your connection and try again."
)


class SealError(Exception):
    """The key cannot be sealed; ``message`` is user-safe, ``code`` a
    ``byok_transport_*`` code for the command-error path."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass(frozen=True)
class TransportKey:
    kid: str
    public_key: str  # base64url, raw 32 bytes


# --- the pure primitive -----------------------------------------------------

def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def seal_with(secret: str, public_key_b64: str, kid: str) -> str:
    """``secret`` sealed to the server key ``(kid, public_key_b64)``. Pure."""
    enc, ct = hpke.seal(_b64d(public_key_b64), BYOK_TRANSPORT_HKDF_INFO,
                        kid.encode("utf-8"), secret.encode("utf-8"))
    return f"{BYOK_TRANSPORT_ENVELOPE_PREFIX}.{kid}.{_b64e(enc + ct)}"


def is_envelope(value: Optional[str]) -> bool:
    return bool(value) and value.startswith(BYOK_TRANSPORT_ENVELOPE_PREFIX + ".")


# --- the server's key (cached) ------------------------------------------------

_lock = threading.Lock()
_cached: Optional[TransportKey] = None
_fetched_at: float = 0.0


def parse_key_payload(data: Any) -> TransportKey:
    """The ``data`` of ``GET /agent/byok/transport-key`` → `TransportKey`.
    Raises `SealError(unavailable)` for anything this client cannot seal to."""
    if not isinstance(data, dict):
        raise SealError(MSG_TRANSPORT_UNAVAILABLE, BYOK_TRANSPORT_UNAVAILABLE_CODE)
    kid = data.get("kid")
    public_key = data.get("public_key")
    algorithm = data.get("algorithm") or BYOK_TRANSPORT_ALGORITHM
    envelope = data.get("envelope") or BYOK_TRANSPORT_ENVELOPE_PREFIX
    try:
        raw = _b64d(public_key) if isinstance(public_key, str) else b""
    except (ValueError, TypeError, base64.binascii.Error):
        raw = b""
    if (not isinstance(kid, str) or not kid or "." in kid or len(raw) != _KEY_LEN
            or algorithm != BYOK_TRANSPORT_ALGORITHM
            or envelope != BYOK_TRANSPORT_ENVELOPE_PREFIX):
        logger.warning("BYOK transport key payload is not one this client can seal to")
        raise SealError(MSG_TRANSPORT_UNAVAILABLE, BYOK_TRANSPORT_UNAVAILABLE_CODE)
    return TransportKey(kid, public_key)


def _fetch() -> TransportKey:
    """One ``GET /agent/byok/transport-key``; every failure is a `SealError`."""
    from ...common.api import get_agent_service

    try:
        response = get_agent_service().get_transport_key()
    except Exception as exc:  # noqa: BLE001 — the HTTP layer raises on non-2xx too
        status = getattr(exc, "status_code", None)
        if status is None:
            # Connection / timeout / retry exhaustion: the NET-* code goes to
            # the log for support; the user is told to check the connection.
            from mixar.config.config import get_server_url
            from ...common.network import classify_network_error, log_network_failure

            failure = classify_network_error(exc, url=get_server_url())
            log_network_failure(logger, failure, "BYOK transport key fetch")
            raise SealError(MSG_TRANSPORT_UNREACHABLE, BYOK_TRANSPORT_UNREACHABLE_CODE) from None
        logger.warning("BYOK transport key fetch refused: HTTP %s", status)
        raise SealError(MSG_TRANSPORT_UNAVAILABLE, BYOK_TRANSPORT_UNAVAILABLE_CODE) from None
    envelope = response.data if isinstance(response.data, dict) else {}
    if not response.success:
        logger.warning("BYOK transport key fetch failed: HTTP %s", response.status_code)
        raise SealError(MSG_TRANSPORT_UNAVAILABLE, BYOK_TRANSPORT_UNAVAILABLE_CODE)
    return parse_key_payload(envelope.get("data"))


def public_key(fetch: Optional[Callable[[], TransportKey]] = None,
               now: Optional[float] = None) -> TransportKey:
    """The server's current key: the cached one while it is under
    `BYOK_TRANSPORT_KEY_TTL_S` old, else fetched. Worker thread only (HTTP
    on a miss). Raises `SealError`."""
    global _cached, _fetched_at
    moment = time.monotonic() if now is None else now
    with _lock:
        if _cached is not None and moment - _fetched_at < BYOK_TRANSPORT_KEY_TTL_S:
            return _cached
        key = (fetch or _fetch)()
        _cached, _fetched_at = key, moment
        return key


def invalidate() -> None:
    """Forget the cached key (the server answered ``byok_transport_key_stale``)."""
    global _cached, _fetched_at
    with _lock:
        _cached, _fetched_at = None, 0.0


def cached_kid() -> Optional[str]:
    with _lock:
        return _cached.kid if _cached is not None else None


def seal(secret: str) -> str:
    """``secret`` sealed to the server's current key. Worker thread only.
    Raises `SealError`; a key is never sent unsealed."""
    try:
        key = public_key()
        return seal_with(secret, key.public_key, key.kid)
    except SealError:
        raise
    except Exception as exc:  # noqa: BLE001 — a bad server point, a crypto fault
        logger.warning("BYOK key sealing failed: %s", type(exc).__name__)
        raise SealError(MSG_TRANSPORT_UNAVAILABLE, BYOK_TRANSPORT_UNAVAILABLE_CODE) from None
