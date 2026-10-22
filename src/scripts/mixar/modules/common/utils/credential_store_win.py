# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Windows Credential Manager entries for `credential_store`, chunked.

Windows caps a generic credential blob at ``CRED_MAX_CREDENTIAL_BLOB_SIZE``
(2560 bytes). A Codex access token alone can exceed that, so a value longer
than one chunk is split across ``<name>#1 … <name>#n`` entries behind a
marker in the head entry; shorter values are one plain entry. Targets are
``<name>@MixarSafeStorage``, the format the C++ shell and `auth/core/auth.py`
use. The raw ``CredRead/Write/DeleteW`` wrappers live beside the Mixar token
code in `auth`; this module only adds the chunking.
"""

from __future__ import annotations

from typing import Optional

# Under CRED_MAX_CREDENTIAL_BLOB_SIZE (2560) with room for the UTF-8 encode.
_WIN_CHUNK_BYTES = 2000
_WIN_CHUNK_MARKER = "\x00mixar-chunks:"


def _target(name: str) -> str:
    from .credential_store import SERVICE_NAME

    return f"{name}@{SERVICE_NAME}"


def _helpers():
    """The Credential Manager helpers live beside the Mixar token code."""
    from mixar.modules.auth.core import auth

    return auth._win_get_password, auth._win_set_password, auth._win_delete_password

def get(name: str) -> Optional[str]:
    get, _set, _delete = _helpers()
    head = get(_target(name))
    if not head:
        return None
    if not head.startswith(_WIN_CHUNK_MARKER):
        return head
    count = int(head[len(_WIN_CHUNK_MARKER):] or 0)
    pieces = []
    for index in range(1, count + 1):
        piece = get(_target(f"{name}#{index}"))
        if not piece:
            return None  # a torn write — treat as absent
        pieces.append(piece)
    return "".join(pieces)


def set_(name: str, value: str) -> bool:
    get, set_, delete = _helpers()
    previous = _chunk_count(get, name)
    encoded = value.encode("utf-8")
    if len(encoded) <= _WIN_CHUNK_BYTES:
        ok = set_(_target(name), name, value)
        count = 0
    else:
        chunks = _split_utf8(value, _WIN_CHUNK_BYTES)
        ok = True
        for index, chunk in enumerate(chunks, start=1):
            ok = set_(_target(f"{name}#{index}"), name, chunk) and ok
        ok = set_(_target(name), name, f"{_WIN_CHUNK_MARKER}{len(chunks)}") and ok
        count = len(chunks)
    for index in range(count + 1, previous + 1):
        delete(_target(f"{name}#{index}"))  # stale tail from a longer value
    return bool(ok)


def delete(name: str) -> bool:
    get, _set, delete = _helpers()
    count = _chunk_count(get, name)
    ok = delete(_target(name))
    for index in range(1, count + 1):
        ok = delete(_target(f"{name}#{index}")) and ok
    return bool(ok)


def _chunk_count(get, name: str) -> int:
    head = get(_target(name))
    if head and head.startswith(_WIN_CHUNK_MARKER):
        try:
            return int(head[len(_WIN_CHUNK_MARKER):] or 0)
        except ValueError:
            return 0
    return 0


def _split_utf8(value: str, limit: int) -> list:
    """Split on character boundaries so no chunk exceeds ``limit`` bytes."""
    chunks, current, size = [], [], 0
    for char in value:
        width = len(char.encode("utf-8"))
        if size + width > limit and current:
            chunks.append("".join(current))
            current, size = [], 0
        current.append(char)
        size += width
    if current:
        chunks.append("".join(current))
    return chunks
