# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Which published-scene links the client will open, copy or store.

The link lives in Scene properties, so a crafted ``.blend`` could carry a
``file://`` / ``javascript:`` / foreign-host URL. A link is safe only when it
is ``https`` with a hostname equal to, or a subdomain of, a trusted host:
the configured API host and its parent domain (``api.mixar.app`` →
``mixar.app``, which covers the viewer at ``scenes.mixar.app``; the client
has no separate viewer-host setting, so the API host is the anchor).
"""

from __future__ import annotations

from typing import Iterable, Optional
from urllib.parse import urlparse


def trusted_hosts(api_url: Optional[str] = None) -> tuple:
    """The API host plus its parent domain when it has three labels or more."""
    if api_url is None:
        try:
            from mixar.config.config import get_server_url

            api_url = get_server_url()
        except Exception:  # noqa: BLE001 — no config: trust nothing
            return ()
    host = (urlparse(str(api_url or "")).hostname or "").lower().rstrip(".")
    if not host:
        return ()
    labels = host.split(".")
    hosts = [host]
    if len(labels) >= 3 and not host.replace(".", "").isdigit():
        hosts.append(".".join(labels[1:]))
    return tuple(hosts)


def is_safe_share_link(url: str, hosts: Optional[Iterable[str]] = None) -> bool:
    try:
        parsed = urlparse(str(url or "").strip())
        host = (parsed.hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        return False
    hosts = tuple(hosts) if hosts is not None else trusted_hosts()
    return any(host == trusted or host.endswith("." + trusted) for trusted in hosts)
