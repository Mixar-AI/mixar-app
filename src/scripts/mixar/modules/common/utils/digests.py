# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Accelerated SHA-256 for large local payloads and checkpoint files."""

from cryptography.hazmat.primitives import hashes


def sha256(data=b""):
    """Return a streaming SHA-256 context; finalize with ``finalize().hex()``."""
    digest = hashes.Hash(hashes.SHA256())
    if data:
        digest.update(data)
    return digest


def sha256_file(path):
    digest = sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.finalize().hex()
