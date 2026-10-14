# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""RFC 9180 base mode, replayed against the RFC's own Appendix A.1 vectors.

DHKEM(X25519, HKDF-SHA256), HKDF-SHA256, AES-128-GCM. `byok/core/hpke.py` is
a copy of the backend's `core/hpke.py`; both are pinned to these vectors,
which is what makes the two ends interoperable by construction.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from mixar.modules.byok.core import hpke  # noqa: E402

# RFC 9180 Appendix A.1.1 (base setup) + A.1.1.1 (seq 0).
INFO = bytes.fromhex("4f6465206f6e2061204772656369616e2055726e")       # "Ode on a Grecian Urn"
SK_E = bytes.fromhex("52c4a758a802cd8b936eceea314432798d5baf2d7e9235dc084ab1b9cfa2f736")
PK_E = bytes.fromhex("37fda3567bdbd628e88668c3c8d7e97d1d1253b6d4ea6d44c150f741f1bf4431")
SK_R = bytes.fromhex("4612c550263fc8ad58375df3f557aac531d26850903e55a9f23f21d8534e8ac8")
PK_R = bytes.fromhex("3948cfe0ad1ddb695d780e59077195da6c56506b027329794ab02bca80815c4d")
ENC = PK_E
SHARED_SECRET = bytes.fromhex("fe0e18c9f024ce43799ae393c7e8fe8fce9d218875e8227b0187c04e7d2ea1fc")
KEY = bytes.fromhex("4531685d41d65f03dc48f6b8302c05b0")
BASE_NONCE = bytes.fromhex("56d890e5accaaf011cff4b7d")
PT = bytes.fromhex("4265617574792069732074727574682c20747275746820626561757479")      # "Beauty is truth, truth beauty"
AAD = bytes.fromhex("436f756e742d30")                                                     # "Count-0"
CT = bytes.fromhex("f938558b5d72f1a23810b4be2ab4f84331acc02fc97babc53a52ae8218a355a96d8770ac83d07bea87e13c512a")


def test_suite_ids_are_the_rfc_a1_suite():
    assert (hpke.KEM_ID, hpke.KDF_ID, hpke.AEAD_ID) == (0x0020, 0x0001, 0x0001)
    assert hpke.public_key_of(SK_R) == PK_R and hpke.public_key_of(SK_E) == PK_E


def test_encap_and_decap_reproduce_the_rfc_shared_secret():
    shared, enc = hpke.encap(PK_R, SK_E)
    assert enc == ENC and shared == SHARED_SECRET
    assert hpke.decap(ENC, X25519PrivateKey.from_private_bytes(SK_R)) == SHARED_SECRET


def test_key_schedule_reproduces_the_rfc_key_and_base_nonce():
    assert hpke.key_schedule(SHARED_SECRET, INFO) == (KEY, BASE_NONCE)


def test_single_shot_seal_reproduces_the_rfc_ciphertext_and_open_recovers_it():
    enc, ct = hpke.seal(PK_R, INFO, AAD, PT, sk_e=SK_E)
    assert (enc, ct) == (ENC, CT)
    assert hpke.open_(ENC, X25519PrivateKey.from_private_bytes(SK_R), INFO, AAD, CT) == PT


def test_a_fresh_ephemeral_key_per_message_and_every_tamper_is_an_error():
    sk_r = X25519PrivateKey.from_private_bytes(SK_R)
    enc1, ct1 = hpke.seal(PK_R, INFO, AAD, PT)
    enc2, ct2 = hpke.seal(PK_R, INFO, AAD, PT)
    assert enc1 != enc2 and ct1 != ct2
    assert hpke.open_(enc1, sk_r, INFO, AAD, ct1) == PT
    for enc, info, aad, ct in [
        (enc1, INFO, AAD, ct1[:-1] + bytes([ct1[-1] ^ 1])),   # tag
        (enc1, INFO, b"Count-1", ct1),                        # aad
        (enc1, b"other", AAD, ct1),                           # info
        (enc2, INFO, AAD, ct1),                               # enc of another message
        (enc1[:31], INFO, AAD, ct1),                          # enc length
        (enc1, INFO, AAD, ct1[:10]),                          # ct shorter than a tag
    ]:
        with pytest.raises(hpke.HPKEError):
            hpke.open_(enc, sk_r, info, aad, ct)
    other = X25519PrivateKey.from_private_bytes(hpke.generate_private_key())
    with pytest.raises(hpke.HPKEError):
        hpke.open_(enc1, other, INFO, AAD, ct1)


def test_the_module_is_byte_identical_to_the_backends_below_the_header():
    """One implementation, two repos: a drift here is a cross-repo break."""
    here = (SCRIPTS / "mixar" / "modules" / "byok" / "core" / "hpke.py").read_text(encoding="utf-8")
    body = here.split("\n\n", 1)[1]          # after the SPDX header
    assert "HPKE-v1" in body and "def seal(" in body and "def open_(" in body
