# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Which published-scene links the client will open, copy or store.

The link lives in Scene properties, so a crafted ``.blend`` could carry a
``file://`` / ``javascript:`` / foreign-host URL. A link is safe only when it
is ``https`` with a plain ASCII hostname that equals a trusted host, or is a
subdomain of ``mixar.app`` when that is the API's parent domain. Trusted
hosts are the configured API host and, under ``mixar.app`` only, its parent
(``api.mixar.app`` → ``mixar.app``, which covers the viewer at
``scenes.mixar.app``); a parent such as ``onrender.com`` is a public suffix
anyone can register under, so other API hosts are trusted exactly. The
client has no separate viewer-host setting, so the API host is the anchor.

Callers open, copy and store ``safe_share_link``'s re-serialized URL, never
the raw string: ``urlparse`` and browsers disagree on backslashes, percent
escapes, whitespace and control characters (``https://evil.com\\.mixar.app``
parses as a ``mixar.app`` host but a browser goes to ``evil.com``), so any of
those is refused outright.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional
from urllib.parse import urlparse, urlunparse

# The one parent domain whose subdomains are all ours.
TRUSTED_PARENT = "mixar.app"
_HOSTNAME = re.compile(r"^[a-z0-9.-]+$")


def trusted_hosts(api_url: Optional[str] = None) -> tuple:
    """The API host, plus ``mixar.app`` when the API host lives under it."""
    if api_url is None:
        try:
            from mixar.config.config import get_server_url

            api_url = get_server_url()
        except Exception:  # noqa: BLE001 — no config: trust nothing
            return ()
    host = (urlparse(str(api_url or "")).hostname or "").lower().rstrip(".")
    if not host:
        return ()
    hosts = [host]
    if host.endswith("." + TRUSTED_PARENT):
        hosts.append(TRUSTED_PARENT)
    return tuple(hosts)


def _unsafe_characters(text: str) -> bool:
    return any(ch == "\\" or ch.isspace() or ord(ch) < 0x20 or ord(ch) == 0x7F
               for ch in text)


def safe_share_link(url: str, hosts: Optional[Iterable[str]] = None) -> str:
    """The re-serialized link when it is safe to open/copy/store, else ""."""
    raw = str(url or "").strip()
    # Checked on the raw text: urlparse silently drops tab/CR/LF.
    if not raw or _unsafe_characters(raw):
        return ""
    try:
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except ValueError:
        return ""
    if (parsed.scheme != "https" or not host or "%" in parsed.netloc
            or "@" in parsed.netloc or not _HOSTNAME.match(host)):
        return ""
    hosts = tuple(hosts) if hosts is not None else trusted_hosts()
    if not any(host == trusted or (trusted == TRUSTED_PARENT and host.endswith("." + trusted))
               for trusted in hosts):
        return ""
    netloc = host if port is None else f"{host}:{port}"
    return urlunparse(("https", netloc, parsed.path, parsed.params, parsed.query,
                       parsed.fragment))


def is_safe_share_link(url: str, hosts: Optional[Iterable[str]] = None) -> bool:
    return bool(safe_share_link(url, hosts))
