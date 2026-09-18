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

Resolution order for the *root set* (first hit wins):

1. **Explicit bundle** — ``MIXAR_CA_BUNDLE``, then ``network.ca_bundle`` in
   ``mixar.json``, then a pre-existing ``REQUESTS_CA_BUNDLE`` /
   ``SSL_CERT_FILE``. It *replaces* the default roots (the same semantics
   as ``REQUESTS_CA_BUNDLE``) and is exported to the variables all bundled
   clients honor, so ``requests``, ``httpx``, ``urllib`` and
   ``websocket-client`` verify against the same file.

   Blender's launcher exports ``SSL_CERT_FILE`` pointing at the *bundled*
   certifi file before Python starts (``bpy_interface.cc``). That is the
   interpreter's default, not an operator's choice, so a value that resolves
   inside the bundled interpreter is ignored here — honoring it made the OS
   trust store below unreachable on macOS and Windows.
2. **OS trust store** via ``truststore`` (what pip uses by default since
   24.2): macOS Security framework, Windows CryptoAPI, or the Linux system
   bundle. Installed by replacing ``ssl.SSLContext`` process-wide, which is
   why this must run before the first TLS handshake.
3. **certifi**, as before, when ``truststore`` is missing or a Linux host
   has no system bundle at all.

Independently of that mode, **additional CA certificates** are loaded on top
of the root set (additive, never replacing):

* ``MIXAR_EXTRA_CA_CERTS`` — ``os.pathsep``-separated files or folders;
* ``network.extra_ca_certs`` in ``mixar.json`` — a string or a list;
* every ``.pem`` / ``.crt`` / ``.cer`` / ``.der`` file in the per-user drop
  folder ``<user config>/mixar/certs`` and the machine-wide folder
  (``/Library/Application Support/Mixar/certs``, ``%ProgramData%\\Mixar\\certs``
  or ``/etc/mixar/certs``).

PEM and DER encodings are both accepted. The certificates are attached by
patching ``ssl.SSLContext`` construction so every context created afterwards
carries them: ``truststore`` forwards a context's own CAs to the OS verifier
as extra anchors, and plain OpenSSL treats ``load_verify_locations`` as
additive, so they count in every mode. An IT team therefore only has to copy the root CA
into the certs folder — no bundle assembly, no keychain change.

Every path logs what was chosen; misconfiguration (a bundle path that does
not exist, an unparsable certificate file) logs at ERROR so it is visible in
production builds.
"""

from __future__ import annotations

import os
import re
import ssl
import sys
from dataclasses import dataclass, replace
from typing import Callable, Iterable, MutableMapping

from mixar.config.logging_config import get_logger

from ..constants import (
    CA_BUNDLE_ENV_VARS,
    CERT_FILE_EXTENSIONS,
    CONFIG_CA_BUNDLE,
    CONFIG_EXTRA_CA_CERTS,
    CONFIG_SECTION,
    ENV_CA_BUNDLE,
    ENV_EXTRA_CA_CERTS,
    LINUX_CA_FILE_CANDIDATES,
    MACHINE_CERTS_DIRS_DARWIN,
    MACHINE_CERTS_DIRS_LINUX,
    MACHINE_CERTS_DIRS_WINDOWS_SUBPATH,
    STANDARD_CA_BUNDLE_ENV_VARS,
    TRUST_MODE_BUNDLE,
    TRUST_MODE_CERTIFI,
    TRUST_MODE_OS,
    USER_CERTS_DIRNAME,
    USER_CERTS_SUBDIR,
)

logger = get_logger(__name__)

SOURCE_ENV_MIXAR = "env:" + ENV_CA_BUNDLE
SOURCE_CONFIG = f"config:{CONFIG_SECTION}.{CONFIG_CA_BUNDLE}"
SOURCE_ENV_EXTRA = "env:" + ENV_EXTRA_CA_CERTS
SOURCE_CONFIG_EXTRA = f"config:{CONFIG_SECTION}.{CONFIG_EXTRA_CA_CERTS}"

_PEM_BLOCK_RE = re.compile(rb"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", re.S)


@dataclass(frozen=True)
class TrustReport:
    mode: str
    bundle_path: str = ""  # only for custom-bundle / certifi-fallback
    source: str = ""
    detail: str = ""
    error: str = ""
    # Additional CA certificates loaded on top of the root set.
    extra_cert_files: tuple[str, ...] = ()
    extra_cert_count: int = 0
    extra_cert_errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExtraCerts:
    """Additional CA certificates gathered by :func:`collect_extra_ca_certs`."""

    pem: str = ""  # concatenated PEM blocks, deduplicated
    files: tuple[str, ...] = ()  # files that contributed at least one block
    count: int = 0
    errors: tuple[str, ...] = ()


_report: TrustReport | None = None


def get_trust_report() -> TrustReport | None:
    """The outcome of the last ``install_trust_store`` call, if any."""
    return _report


def _config_section(config_getter: Callable[[], dict] | None) -> dict:
    if config_getter is None:
        return {}
    try:
        section = (config_getter() or {}).get(CONFIG_SECTION) or {}
        return section if isinstance(section, dict) else {}
    except Exception as exc:  # config must never break startup
        logger.debug("Network config unavailable: %s", exc)
        return {}


def _config_bundle(config_getter: Callable[[], dict] | None) -> str:
    return str(_config_section(config_getter).get(CONFIG_CA_BUNDLE) or "").strip()


def _config_extra_certs(config_getter: Callable[[], dict] | None) -> list[str]:
    value = _config_section(config_getter).get(CONFIG_EXTRA_CA_CERTS)
    if isinstance(value, str):
        return [part.strip() for part in value.split(os.pathsep) if part.strip()]
    if isinstance(value, (list, tuple)):
        return [str(part).strip() for part in value if str(part).strip()]
    return []


def _certifi_path() -> str:
    try:
        import certifi

        return certifi.where()
    except Exception:
        return ""


def _normalize(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


def _is_bundled_default(path: str) -> bool:
    """Whether *path* is the interpreter's own default bundle, not an override.

    Blender exports ``SSL_CERT_FILE=<bundled certifi>`` at launch so plain
    OpenSSL clients work out of the box. Treating that as an operator's
    explicit bundle would pin trust to certifi and skip the OS store, which
    is the opposite of what an enterprise install needs.
    """
    if not path:
        return False
    try:
        resolved = _normalize(path)
    except (OSError, ValueError):
        return False
    certifi_path = _certifi_path()
    if certifi_path and resolved == _normalize(certifi_path):
        return True
    for prefix in {sys.prefix, sys.base_prefix, sys.exec_prefix}:
        if not prefix:
            continue
        root = _normalize(prefix).rstrip(os.sep) + os.sep
        if resolved.startswith(root):
            return True
    return False


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
        if not value:
            continue
        if _is_bundled_default(value):
            logger.debug("Ignoring %s=%s: the interpreter's bundled default, not an override", name, value)
            continue
        return value, "env:" + name
    return "", ""


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


# --- Additional CA certificates ---------------------------------------------


def user_certs_dir() -> str:
    """``<user config>/mixar/certs``: the per-user drop folder. Empty outside Blender."""
    try:
        import bpy

        base = bpy.utils.user_resource("CONFIG", path=USER_CERTS_SUBDIR, create=False)
    except Exception:
        return ""
    if not isinstance(base, str) or not base:
        return ""
    return os.path.join(base, USER_CERTS_DIRNAME)


def machine_certs_dirs(
    platform: str | None = None,
    environ: MutableMapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Machine-wide drop folders for *platform* (default: the running one)."""
    platform = sys.platform if platform is None else platform
    if platform == "darwin":
        return MACHINE_CERTS_DIRS_DARWIN
    if platform.startswith("win"):
        environ = os.environ if environ is None else environ
        base = environ.get("ProgramData") or environ.get("PROGRAMDATA") or ""
        return (os.path.join(base, *MACHINE_CERTS_DIRS_WINDOWS_SUBPATH),) if base else ()
    return MACHINE_CERTS_DIRS_LINUX


def default_certs_search_dirs(environ: MutableMapping[str, str] | None = None) -> tuple[str, ...]:
    """Folders scanned for certificates when nothing explicit is configured."""
    return (user_certs_dir(), *machine_certs_dirs(None, environ))


def _cert_files_in(path: str) -> list[str]:
    """*path* itself when it is a file, else its certificate files (sorted)."""
    if not os.path.isdir(path):
        return [path]
    try:
        names = sorted(os.listdir(path))
    except OSError as exc:
        logger.error("Cannot list certificate folder %s: %s", path, exc)
        return []
    files = []
    for name in names:
        full = os.path.join(path, name)
        if name.startswith("."):
            continue
        if name.lower().endswith(CERT_FILE_EXTENSIONS) and os.path.isfile(full):
            files.append(full)
    return files


def _pem_blocks(data: bytes) -> list[str]:
    """PEM certificate blocks in *data*; DER input is converted to one block."""
    blocks = [match.group(0).decode("ascii", "replace") for match in _PEM_BLOCK_RE.finditer(data)]
    if blocks:
        return blocks
    return [ssl.DER_cert_to_PEM_cert(data).strip()]


def _check_certificates(pem: str) -> None:
    """Raise if OpenSSL cannot parse *pem* (garbage, truncated, not X.509)."""
    ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).load_verify_locations(cadata=pem)


def collect_extra_ca_certs(
    config_getter: Callable[[], dict] | None,
    environ: MutableMapping[str, str],
    search_dirs: Iterable[str] | None = None,
) -> ExtraCerts:
    """Gather every additional CA certificate configured or dropped in a certs folder.

    *search_dirs* overrides the default drop folders (tests); explicit
    sources (environment, config) are always consulted.
    """
    explicit: list[tuple[str, str]] = []
    for raw in (environ.get(ENV_EXTRA_CA_CERTS) or "").split(os.pathsep):
        if raw.strip():
            explicit.append((raw.strip(), SOURCE_ENV_EXTRA))
    for raw in _config_extra_certs(config_getter):
        explicit.append((raw, SOURCE_CONFIG_EXTRA))
    if search_dirs is None:
        search_dirs = default_certs_search_dirs(environ)

    errors: list[str] = []
    files: list[str] = []
    for path, source in explicit:
        path = os.path.expanduser(path)
        if not os.path.exists(path):
            errors.append(f"{source}: {path} does not exist")
            logger.error("Extra CA certificates from %s do not exist: %s", source, path)
            continue
        files.extend(_cert_files_in(path))
    for folder in search_dirs:
        if folder and os.path.isdir(folder):
            files.extend(_cert_files_in(folder))

    seen_files: set[str] = set()
    seen_blocks: set[str] = set()
    blocks: list[str] = []
    loaded: list[str] = []
    for file in files:
        key = _normalize(file)
        if key in seen_files:
            continue
        seen_files.add(key)
        try:
            with open(file, "rb") as handle:
                pems = _pem_blocks(handle.read())
            _check_certificates("\n".join(pems))
        except Exception as exc:
            errors.append(f"{file}: {exc}")
            logger.error("Skipping CA certificate file %s: %s", file, exc)
            continue
        fresh = [block for block in pems if block not in seen_blocks]
        seen_blocks.update(fresh)
        blocks.extend(fresh)
        if fresh:
            loaded.append(file)

    pem = "\n".join(blocks) + ("\n" if blocks else "")
    return ExtraCerts(pem=pem, files=tuple(loaded), count=len(blocks), errors=tuple(errors))


def _real_ssl_context_class() -> type:
    """CPython's ``ssl.SSLContext`` even after truststore injected its subclass."""
    for cls in ssl.SSLContext.__mro__:
        if cls.__module__ == "ssl" and cls.__name__ == "SSLContext":
            return cls
    return ssl.SSLContext


def _refresh_requests_preloaded_context() -> None:
    """Rebuild the context ``requests`` created at import, if it already did.

    requests >= 2.32 caches one verified context per process; it predates
    the patch, so it would keep verifying without the extra certificates.
    """
    adapters = sys.modules.get("requests.adapters")
    if adapters is None or getattr(adapters, "_preloaded_ssl_context", None) is None:
        return
    try:
        try:
            from urllib3.util.ssl_ import create_urllib3_context

            context = create_urllib3_context()
        except Exception:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        certifi_path = _certifi_path()
        if certifi_path and os.path.isfile(certifi_path):
            context.load_verify_locations(cafile=certifi_path)
        adapters._preloaded_ssl_context = context
    except Exception as exc:
        logger.error("Could not refresh requests' preloaded SSL context: %s", exc)


# State of the ``ssl.SSLContext.__new__`` patch (see ``_install_extra_certs``).
_extra_pem = ""
_patched_class: type | None = None
_original_new = None


def _patched_ssl_context_new(cls, *args, **kwargs):
    self = _original_new(cls, *args, **kwargs)
    if _extra_pem:
        try:
            # The C-level loader on the *real* class: every instance, including
            # truststore's subclass, is one at that level.
            _patched_class.load_verify_locations(self, cadata=_extra_pem)
        except Exception as exc:
            logger.error("Could not attach the extra CA certificates to a new SSL context: %s", exc)
    return self


def _uninstall_extra_certs() -> None:
    global _extra_pem, _patched_class, _original_new
    _extra_pem = ""
    if _patched_class is not None:
        # ssl.py defines __new__ as a function, which class creation wraps in
        # staticmethod; assigning later does not, so wrap it back explicitly.
        _patched_class.__new__ = staticmethod(_original_new)
        _patched_class = None
        _original_new = None


def _install_extra_certs(extra: ExtraCerts) -> None:
    """Make every ``SSLContext`` created from now on trust *extra* as well.

    Patches ``__new__`` on CPython's ``ssl.SSLContext`` (a Python class) to
    load the certificates into each new instance. The class object itself
    is left in place: the stdlib's own property setters look ``SSLContext``
    up in the ``ssl`` module globals and recurse when that name is rebound
    to a subclass — the reason truststore wraps by composition. truststore's
    context builds a real ``SSLContext`` internally, so it is covered too,
    and it forwards the loaded CAs to the OS verifier as extra anchors.
    Idempotent: reinstalling only swaps the certificate data.
    """
    global _extra_pem, _patched_class, _original_new
    if not extra.count:
        _uninstall_extra_certs()
        return
    if _patched_class is None:
        real = _real_ssl_context_class()
        _original_new = real.__new__
        _patched_class = real
        real.__new__ = staticmethod(_patched_ssl_context_new)
    _extra_pem = extra.pem
    _refresh_requests_preloaded_context()


def install_trust_store(
    config_getter: Callable[[], dict] | None = None,
    environ: MutableMapping[str, str] | None = None,
    force: bool = False,
    search_dirs: Iterable[str] | None = None,
) -> TrustReport:
    """Install the trust configuration once for the process.

    Idempotent: later calls return the first report unless ``force`` is set
    (tests only — ``truststore.inject_into_ssl`` itself is safe to repeat).
    *search_dirs* overrides the certificate drop folders (tests only).
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
            report = replace(_install_os_trust_store(environ), error=report.error)
    else:
        report = _install_os_trust_store(environ)

    extra = collect_extra_ca_certs(config_getter, environ, search_dirs)
    errors = list(extra.errors)
    try:
        _install_extra_certs(extra)
    except Exception as exc:
        logger.error("Could not install the extra CA certificates: %s", exc, exc_info=True)
        errors.append(f"install: {exc}")
        extra = replace(extra, count=0, files=())
    if extra.count:
        logger.info(
            "Network trust: %d additional CA certificate(s) from %s",
            extra.count,
            ", ".join(extra.files),
        )
    report = replace(
        report,
        extra_cert_files=extra.files,
        extra_cert_count=extra.count,
        extra_cert_errors=tuple(errors),
    )

    _report = report
    return report
