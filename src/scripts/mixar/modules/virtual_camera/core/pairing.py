# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pairing state: token generation, LAN address discovery, pairing URL."""

from __future__ import annotations

import secrets
import socket

from ..constants import TOKEN_LENGTH


def generate_token() -> str:
    """URL-safe pairing token; regenerated on every server start."""
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "".join(secrets.choice(alphabet) for _ in range(TOKEN_LENGTH))


def lan_addresses() -> list[str]:
    """Best-effort list of non-loopback IPv4 addresses, preferred first.

    The UDP-connect trick learns the address of the default-route interface
    without sending a packet; getaddrinfo fills in any extras (multi-homed
    hosts). Order matters — the first entry lands in the QR code.
    """
    addresses: list[str] = []

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("203.0.113.1", 9))  # TEST-NET-3, never actually sent
        primary = sock.getsockname()[0]
        if not primary.startswith("127."):
            addresses.append(primary)
    except OSError:
        pass
    finally:
        sock.close()

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addr = info[4][0]
            if not addr.startswith("127.") and addr not in addresses:
                addresses.append(addr)
    except OSError:
        pass

    return addresses


def pairing_url(host: str, port: int, token: str, *, tls: bool) -> str:
    scheme = "https" if tls else "http"
    return f"{scheme}://{host}:{port}/?t={token}"
