# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Startup entry point: configure proxy and trust before the first request.

Called from ``startup/bootstrap/__init__.py`` (bootstrap phase 2), ahead of
every bootstrap module, so no TLS context or HTTP connection exists yet. Never
raises: a broken network configuration must degrade to library defaults,
not prevent the app from starting.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, MutableMapping

from mixar.config.logging_config import get_logger

from .proxy import ProxyReport, configure_proxy
from .trust import TrustReport, get_trust_report, install_trust_store

logger = get_logger(__name__)


@dataclass(frozen=True)
class NetworkReport:
    trust: TrustReport | None
    proxy: ProxyReport | None


_report: NetworkReport | None = None


def _default_config_getter() -> Callable[[], dict] | None:
    try:
        from mixar.config.config import get_config

        return get_config
    except Exception as exc:  # outside Blender (tests, tooling)
        logger.debug("mixar.config unavailable for network setup: %s", exc)
        return None


def configure_network(
    config_getter: Callable[[], dict] | None = None,
    environ: MutableMapping[str, str] | None = None,
    force: bool = False,
) -> NetworkReport:
    """Resolve proxy, then trust, once per process."""
    global _report
    if _report is not None and not force:
        return _report
    environ = os.environ if environ is None else environ
    if config_getter is None:
        config_getter = _default_config_getter()

    proxy = None
    try:
        proxy = configure_proxy(config_getter, environ)
    except Exception as exc:
        logger.error("Proxy configuration failed; using library defaults: %s", exc, exc_info=True)

    trust = None
    try:
        trust = install_trust_store(config_getter, environ, force=force)
    except Exception as exc:
        logger.error("Trust store setup failed; using certifi defaults: %s", exc, exc_info=True)

    _report = NetworkReport(trust=trust, proxy=proxy)
    return _report


def network_diagnostics() -> dict:
    """Compact, log-safe summary of the effective network configuration."""
    trust = get_trust_report()
    proxy = _report.proxy if _report else None
    return {
        "trust": trust.mode if trust else "unconfigured",
        "ca_bundle": trust.bundle_path if trust and trust.bundle_path else "",
        "trust_error": trust.error if trust and trust.error else "",
        "proxy": proxy.url if proxy and proxy.url else "none",
        "proxy_source": proxy.source if proxy else "unconfigured",
        "proxy_error": proxy.error if proxy and proxy.error else "",
    }
