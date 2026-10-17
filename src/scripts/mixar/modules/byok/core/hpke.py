# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""RFC 9180 Hybrid Public Key Encryption, base mode, single-shot.

Suite: DHKEM(X25519, HKDF-SHA256) (kem_id 0x0020), HKDF-SHA256 (kdf_id
0x0001), AES-128-GCM (aead_id 0x0001) — the suite RFC 9180 publishes test
vectors for (Appendix A.1), which `tests/test_byok_hpke.py` replays
byte for byte. This file is a copy of the backend's ``core/hpke.py``, pinned
to the same vectors, so the two ends are interoperable by construction, not
by convention. Keep them identical below the header.

Only what BYOK transport needs is here: `seal` (sender) and `open_` (recipient)
for one message each — the first (seq 0) nonce of a context, no exporter, no
PSK / auth modes. Built on the `cryptography` package both repos ship.
"""

from __future__ import annotations

from typing import Optional, Tuple

from cryptography.hazmat.primitives import hashes, hmac, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDFExpand

KEM_ID = 0x0020      # DHKEM(X25519, HKDF-SHA256)
KDF_ID = 0x0001      # HKDF-SHA256
AEAD_ID = 0x0001     # AES-128-GCM
MODE_BASE = 0x00

N_SECRET = 32        # KEM shared secret
N_PK = 32            # X25519 public key / enc
N_K = 16             # AES-128-GCM key
N_N = 12             # AES-GCM nonce
N_T = 16             # AES-GCM tag

_VERSION = b"HPKE-v1"
_KEM_SUITE_ID = b"KEM" + KEM_ID.to_bytes(2, "big")
_SUITE_ID = b"HPKE" + KEM_ID.to_bytes(2, "big") + KDF_ID.to_bytes(2, "big") + AEAD_ID.to_bytes(2, "big")


class HPKEError(ValueError):
    """A message this recipient cannot open (bad point, bad tag, bad length)."""


# --- RFC 9180 § 4: labeled KDF ------------------------------------------------

def _extract(salt: bytes, ikm: bytes) -> bytes:
    """HKDF-Extract (RFC 5869): HMAC-SHA256(salt, ikm), an empty salt being 32 zero bytes."""
    mac = hmac.HMAC(salt or bytes(32), hashes.SHA256())
    mac.update(ikm)
    return mac.finalize()


def _labeled_extract(suite_id: bytes, salt: bytes, label: bytes, ikm: bytes) -> bytes:
    return _extract(salt, _VERSION + suite_id + label + ikm)


def _labeled_expand(suite_id: bytes, prk: bytes, label: bytes, info: bytes, length: int) -> bytes:
    labeled_info = length.to_bytes(2, "big") + _VERSION + suite_id + label + info
    return HKDFExpand(algorithm=hashes.SHA256(), length=length, info=labeled_info).derive(prk)


# --- § 4.1 DHKEM(X25519) -------------------------------------------------------

def _raw_public(key: X25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def _extract_and_expand(dh: bytes, kem_context: bytes) -> bytes:
    eae_prk = _labeled_extract(_KEM_SUITE_ID, b"", b"eae_prk", dh)
    return _labeled_expand(_KEM_SUITE_ID, eae_prk, b"shared_secret", kem_context, N_SECRET)


def encap(pk_r: bytes, sk_e: Optional[bytes] = None) -> Tuple[bytes, bytes]:
    """``(shared_secret, enc)`` for recipient public key ``pk_r``. ``sk_e``
    (raw 32 bytes) fixes the ephemeral key — test vectors only."""
    eph = X25519PrivateKey.from_private_bytes(sk_e) if sk_e else X25519PrivateKey.generate()
    enc = _raw_public(eph)
    dh = eph.exchange(X25519PublicKey.from_public_bytes(pk_r))
    return _extract_and_expand(dh, enc + pk_r), enc


def decap(enc: bytes, sk_r: X25519PrivateKey) -> bytes:
    if len(enc) != N_PK:
        raise HPKEError("enc length")
    try:
        dh = sk_r.exchange(X25519PublicKey.from_public_bytes(enc))
    except Exception as exc:  # noqa: BLE001 — a low-order or invalid point
        raise HPKEError("enc point") from exc
    return _extract_and_expand(dh, enc + _raw_public(sk_r))


# --- § 5.1 key schedule (base mode) ----------------------------------------------

def key_schedule(shared_secret: bytes, info: bytes) -> Tuple[bytes, bytes]:
    """``(key, base_nonce)`` of the base-mode context for ``info``."""
    psk_id_hash = _labeled_extract(_SUITE_ID, b"", b"psk_id_hash", b"")
    info_hash = _labeled_extract(_SUITE_ID, b"", b"info_hash", info)
    context = bytes([MODE_BASE]) + psk_id_hash + info_hash
    secret = _labeled_extract(_SUITE_ID, shared_secret, b"secret", b"")
    key = _labeled_expand(_SUITE_ID, secret, b"key", context, N_K)
    base_nonce = _labeled_expand(_SUITE_ID, secret, b"base_nonce", context, N_N)
    return key, base_nonce


# --- § 6.1 single-shot ---------------------------------------------------------------

def seal(pk_r: bytes, info: bytes, aad: bytes, pt: bytes, sk_e: Optional[bytes] = None) -> Tuple[bytes, bytes]:
    """``(enc, ct)``: ``pt`` sealed to ``pk_r`` (raw 32 bytes) as the first
    message (seq 0) of a fresh base-mode context."""
    shared_secret, enc = encap(pk_r, sk_e)
    key, base_nonce = key_schedule(shared_secret, info)
    return enc, AESGCM(key).encrypt(base_nonce, pt, aad)


def open_(enc: bytes, sk_r: X25519PrivateKey, info: bytes, aad: bytes, ct: bytes) -> bytes:
    """The plaintext of ``(enc, ct)`` for recipient ``sk_r``; `HPKEError` otherwise."""
    if len(ct) < N_T:
        raise HPKEError("ct length")
    key, base_nonce = key_schedule(decap(enc, sk_r), info)
    try:
        return AESGCM(key).decrypt(base_nonce, ct, aad)
    except Exception as exc:  # noqa: BLE001 — a bad tag is the only failure here
        raise HPKEError("tag") from exc


def generate_private_key() -> bytes:
    """A fresh raw X25519 private key (32 bytes)."""
    return X25519PrivateKey.generate().private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )


def public_key_of(sk: bytes) -> bytes:
    return _raw_public(X25519PrivateKey.from_private_bytes(sk))


__all__ = [
    "AEAD_ID", "KDF_ID", "KEM_ID", "HPKEError", "N_K", "N_N", "N_PK", "N_T",
    "decap", "encap", "generate_private_key", "key_schedule", "open_", "public_key_of", "seal",
]
