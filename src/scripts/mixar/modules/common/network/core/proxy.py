# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Outbound proxy configuration shared by every bundled client.

``requests``, ``httpx`` and ``urllib`` read the ``HTTPS_PROXY`` family of
environment variables (and, on Windows/macOS, the static system proxy);
``websocket-client`` reads only the environment. Rather than threading proxy
arguments through every call site, one explicit proxy is resolved at startup
and exported to the environment so all clients agree, and the loopback hosts
Mixar talks to itself on are always excluded.

Resolution order (first hit wins):
1. ``MIXAR_PROXY_URL`` environment variable
2. ``network.proxy_url`` in ``mixar.json``
3. ``HTTPS_PROXY`` / ``HTTP_PROXY`` already present in the environment
4. The operating system's static proxy (``urllib.request.getproxies()``)

PAC / WPAD auto-configuration is not supported: the proxy URL must be set
explicitly. SOCKS proxies are rejected because the required client
libraries are not bundled.
"""

from __future__ import annotations

import os
import urllib.request
from dataclasses import dataclass
from typing import Callable, MutableMapping
from urllib.parse import urlsplit, urlunsplit

from mixar.config.logging_config import get_logger

from ..constants import (
    CONFIG_NO_PROXY,
    CONFIG_PROXY_URL,
    CONFIG_SECTION,
    ENV_NO_PROXY,
    ENV_PROXY_URL,
    LOOPBACK_NO_PROXY,
    NO_PROXY_ENV_VARS,
    PROXY_ENV_VARS,
    SUPPORTED_PROXY_SCHEMES,
    UNSUPPORTED_PROXY_SCHEMES,
)

logger = get_logger(__name__)

SOURCE_ENV_MIXAR = "env:" + ENV_PROXY_URL
SOURCE_CONFIG = f"config:{CONFIG_SECTION}.{CONFIG_PROXY_URL}"
SOURCE_ENV_STANDARD = "env:HTTPS_PROXY"
SOURCE_SYSTEM = "system"
SOURCE_NONE = "none"


@dataclass(frozen=True)
class ProxyReport:
    url: str  # credentials redacted; "" when direct
    source: str
    no_proxy: str
    error: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.url)


def redact_proxy_url(url: str) -> str:
    """Hide the password (and username) in a proxy URL for logs."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<unparseable>"
    if not parts.username and not parts.password:
        return url
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    netloc = f"{parts.username or ''}:***@{host}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def validate_proxy_url(url: str) -> str | None:
    """Return an error string if ``url`` cannot be used, else None."""
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        return f"unparseable proxy URL: {exc}"
    scheme = (parts.scheme or "").lower()
    if scheme in UNSUPPORTED_PROXY_SCHEMES:
        return (
            f"{scheme}:// proxies are not supported (SOCKS client libraries are not "
            "bundled); use an http:// or https:// proxy"
        )
    if scheme not in SUPPORTED_PROXY_SCHEMES:
        return f"proxy URL must start with http:// or https:// (got {scheme or 'no scheme'}://)"
    if not parts.hostname:
        return "proxy URL has no host"
    return None


def _config_section(config_getter: Callable[[], dict] | None) -> dict:
    if config_getter is None:
        return {}
    try:
        section = (config_getter() or {}).get(CONFIG_SECTION) or {}
    except Exception as exc:  # config must never break startup
        logger.debug("Network config unavailable: %s", exc)
        return {}
    return section if isinstance(section, dict) else {}


def _first_env(environ: MutableMapping[str, str], names) -> str:
    for name in names:
        value = (environ.get(name) or "").strip()
        if value:
            return value
    return ""


def resolve_proxy_url(
    config_getter: Callable[[], dict] | None,
    environ: MutableMapping[str, str],
) -> tuple[str, str]:
    """Return ``(proxy_url, source)``; ``("", "none")`` means connect directly."""
    explicit = (environ.get(ENV_PROXY_URL) or "").strip()
    if explicit:
        return explicit, SOURCE_ENV_MIXAR

    configured = str(_config_section(config_getter).get(CONFIG_PROXY_URL) or "").strip()
    if configured:
        return configured, SOURCE_CONFIG

    standard = _first_env(environ, PROXY_ENV_VARS)
    if standard:
        return standard, SOURCE_ENV_STANDARD

    try:
        system = urllib.request.getproxies()
    except Exception as exc:
        logger.debug("System proxy lookup failed: %s", exc)
        system = {}
    for key in ("https", "http"):
        value = (system.get(key) or "").strip()
        if value:
            return value, SOURCE_SYSTEM
    return "", SOURCE_NONE


def _merged_no_proxy(config_getter, environ) -> str:
    entries: list[str] = []
    sources = [
        environ.get(ENV_NO_PROXY, ""),
        str(_config_section(config_getter).get(CONFIG_NO_PROXY) or ""),
        _first_env(environ, NO_PROXY_ENV_VARS),
        ",".join(LOOPBACK_NO_PROXY),
    ]
    for raw in sources:
        for item in raw.split(","):
            item = item.strip()
            if item and item not in entries:
                entries.append(item)
    return ",".join(entries)


def configure_proxy(
    config_getter: Callable[[], dict] | None = None,
    environ: MutableMapping[str, str] | None = None,
) -> ProxyReport:
    """Resolve the proxy once and export it so every client sees the same thing."""
    environ = os.environ if environ is None else environ

    no_proxy = _merged_no_proxy(config_getter, environ)
    for name in NO_PROXY_ENV_VARS:
        environ[name] = no_proxy

    url, source = resolve_proxy_url(config_getter, environ)
    if not url:
        logger.info("Network proxy: none (direct connection); NO_PROXY=%s", no_proxy)
        return ProxyReport(url="", source=SOURCE_NONE, no_proxy=no_proxy)

    error = validate_proxy_url(url)
    if error:
        # Visible in Prod builds (ERROR level) because a bad proxy setting is
        # the kind of misconfiguration support gets called about.
        logger.error("Ignoring proxy from %s: %s", source, error)
        return ProxyReport(url="", source=source, no_proxy=no_proxy, error=error)

    if source != SOURCE_ENV_STANDARD:
        # Export so websocket-client (env-only) and every other client use
        # the same proxy. An explicit Mixar setting overrides the ambient
        # environment on purpose; the standard variables are left untouched
        # when they are the source.
        for name in PROXY_ENV_VARS:
            environ[name] = url

    redacted = redact_proxy_url(url)
    logger.info("Network proxy: %s (from %s); NO_PROXY=%s", redacted, source, no_proxy)
    return ProxyReport(url=redacted, source=source, no_proxy=no_proxy)
