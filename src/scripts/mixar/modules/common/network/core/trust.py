# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Certificate trust for every HTTPS / WSS client bundled with Mixar.

Blender's Python ships ``certifi``: a fixed list of public root CAs.
Enterprise networks commonly run TLS-inspecting proxies that re-sign traffic
with a private root CA that IT installs in the operating system's trust
store. Browsers accept it; certifi does not. The result is that the web
login succeeds while every request from the app fails with a certificate
error that ``requests`` reports as a generic connection failure.

Resolution order (first hit wins):

1. **Explicit bundle** — ``MIXAR_CA_BUNDLE``, then ``network.ca_bundle`` in
   ``mixar.json``, then a pre-existing ``REQUESTS_CA_BUNDLE`` /
   ``SSL_CERT_FILE``. It *replaces* the default roots (the same semantics
   as ``REQUESTS_CA_BUNDLE``) and is exported to the variables all bundled
   clients honor, so ``requests``, ``httpx``, ``urllib`` and
   ``websocket-client`` verify against the same file.
2. **OS trust store** via ``truststore`` (what pip uses by default since
   24.2): macOS Security framework, Windows CryptoAPI, or the Linux system
   bundle. Installed by replacing ``ssl.SSLContext`` process-wide, which is
   why this must run before the first TLS handshake.
3. **certifi**, as before, when ``truststore`` is missing or a Linux host
   has no system bundle at all.

Every path logs what was chosen; misconfiguration (a bundle path that does
not exist) logs at ERROR so it is visible in production builds.
"""

from __future__ import annotations

import os
import ssl
import sys
from dataclasses import dataclass
from typing import Callable, MutableMapping

from mixar.config.logging_config import get_logger

from ..constants import (
    CA_BUNDLE_ENV_VARS,
    CONFIG_CA_BUNDLE,
    CONFIG_SECTION,
    ENV_CA_BUNDLE,
    LINUX_CA_FILE_CANDIDATES,
    STANDARD_CA_BUNDLE_ENV_VARS,
    TRUST_MODE_BUNDLE,
    TRUST_MODE_CERTIFI,
    TRUST_MODE_OS,
)

logger = get_logger(__name__)

SOURCE_ENV_MIXAR = "env:" + ENV_CA_BUNDLE
SOURCE_CONFIG = f"config:{CONFIG_SECTION}.{CONFIG_CA_BUNDLE}"


@dataclass(frozen=True)
class TrustReport:
    mode: str
    bundle_path: str = ""  # only for custom-bundle / certifi-fallback
    source: str = ""
    detail: str = ""
    error: str = ""


_report: TrustReport | None = None


def get_trust_report() -> TrustReport | None:
    """The outcome of the last ``install_trust_store`` call, if any."""
    return _report


def _config_bundle(config_getter: Callable[[], dict] | None) -> str:
    if config_getter is None:
        return ""
    try:
        section = (config_getter() or {}).get(CONFIG_SECTION) or {}
        return str(section.get(CONFIG_CA_BUNDLE) or "").strip() if isinstance(section, dict) else ""
    except Exception as exc:  # config must never break startup
        logger.debug("Network config unavailable: %s", exc)
        return ""


def resolve_ca_bundle_override(
    config_getter: Callable[[], dict] | None,
    environ: MutableMapping[str, str],
) -> tuple[str, str]:
    """Return ``(path, source)`` of an explicit bundle, or ``("", "")``."""
    explicit = (environ.get(ENV_CA_BUNDLE) or "").strip()
    if explicit:
        return explicit, SOURCE_ENV_MIXAR
    configured = _config_bundle(config_getter)
    if configured:
        return configured, SOURCE_CONFIG
    for name in STANDARD_CA_BUNDLE_ENV_VARS:
        value = (environ.get(name) or "").strip()
        if value:
            return value, "env:" + name
    return "", ""


def _certifi_path() -> str:
    try:
        import certifi

        return certifi.where()
    except Exception:
        return ""


def _linux_system_ca_available() -> bool:
    """Whether truststore will find a usable CA bundle on this Linux host."""
    defaults = ssl.get_default_verify_paths()
    if defaults.cafile and os.path.isfile(defaults.cafile):
        return True
    if defaults.capath and os.path.isdir(defaults.capath) and os.listdir(defaults.capath):
        return True
    return any(os.path.isfile(path) for path in LINUX_CA_FILE_CANDIDATES)


def _export_bundle(environ: MutableMapping[str, str], path: str) -> None:
    for name in CA_BUNDLE_ENV_VARS:
        environ[name] = path


def _install_custom_bundle(path: str, source: str, environ) -> TrustReport:
    if not os.path.isfile(path):
        logger.error(
            "CA bundle from %s does not exist: %s — falling back to the OS trust store",
            source,
            path,
        )
        return TrustReport(mode="", error=f"{source} points to a missing file: {path}")
    _export_bundle(environ, path)
    logger.info("Network trust: custom CA bundle %s (from %s)", path, source)
    return TrustReport(mode=TRUST_MODE_BUNDLE, bundle_path=path, source=source)


def _install_os_trust_store(environ) -> TrustReport:
    try:
        import truststore
    except ImportError as exc:
        certifi_path = _certifi_path()
        logger.error(
            "truststore is not installed; TLS will trust only certifi's public CAs "
            "(corporate TLS inspection will fail): %s",
            exc,
        )
        return TrustReport(
            mode=TRUST_MODE_CERTIFI,
            bundle_path=certifi_path,
            source="truststore-missing",
            error=str(exc),
        )

    detail = ""
    mode = TRUST_MODE_OS
    bundle_path = ""
    if sys.platform.startswith("linux") and not _linux_system_ca_available():
        # truststore on Linux relies on the OpenSSL default paths or a known
        # distro bundle. When neither exists (minimal container images),
        # point OpenSSL at certifi so verification keeps working as before.
        certifi_path = _certifi_path()
        if certifi_path:
            environ["SSL_CERT_FILE"] = certifi_path
            mode = TRUST_MODE_CERTIFI
            bundle_path = certifi_path
            detail = "no system CA bundle found on this Linux host"

    truststore.inject_into_ssl()
    if mode == TRUST_MODE_OS:
        logger.info("Network trust: OS trust store (truststore %s)", _truststore_version())
    else:
        logger.info("Network trust: certifi fallback (%s)", detail)
    return TrustReport(mode=mode, bundle_path=bundle_path, source="truststore", detail=detail)


def _truststore_version() -> str:
    try:
        from importlib.metadata import version

        return version("truststore")
    except Exception:
        return "?"


def install_trust_store(
    config_getter: Callable[[], dict] | None = None,
    environ: MutableMapping[str, str] | None = None,
    force: bool = False,
) -> TrustReport:
    """Install the trust configuration once for the process.

    Idempotent: later calls return the first report unless ``force`` is set
    (tests only — ``truststore.inject_into_ssl`` itself is safe to repeat).
    """
    global _report
    if _report is not None and not force:
        return _report
    environ = os.environ if environ is None else environ

    path, source = resolve_ca_bundle_override(config_getter, environ)
    report = None
    if path:
        report = _install_custom_bundle(path, source, environ)
        if report.mode == "":
            error = report.error
            report = _install_os_trust_store(environ)
            report = TrustReport(
                mode=report.mode,
                bundle_path=report.bundle_path,
                source=report.source,
                detail=report.detail,
                error=error,
            )
    else:
        report = _install_os_trust_store(environ)

    _report = report
    return report
