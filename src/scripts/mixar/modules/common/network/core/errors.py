# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Reduce any outbound network exception to one actionable failure.

The bundled clients (``requests``, ``httpx``, ``urllib``, ``http.client``,
``websocket-client``) raise different exception trees for the same underlying
problem, and ``requests`` in particular folds TLS, proxy and firewall failures
into one ``ConnectionError``. Support cannot act on "Unable to connect to
server". This module walks the exception chain and matches the root cause
against known signatures, producing a short user message, a support code and
an IT-facing hint.

Classification is name/message based on purpose: it must not import the HTTP
libraries (some are optional, all are slow to import) and it must stay
correct if a library is upgraded.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from ..constants import (
    PROXY_ENV_VARS,
    FAILURE_DNS,
    FAILURE_PROXY,
    FAILURE_REFUSED,
    FAILURE_RESET,
    FAILURE_TIMEOUT,
    FAILURE_TLS_HANDSHAKE,
    FAILURE_TLS_VERIFY,
    FAILURE_UNKNOWN,
    FAILURE_UNREACHABLE,
    SUPPORT_CODES,
)


@dataclass(frozen=True)
class NetworkFailure:
    """One classified outbound failure."""

    kind: str
    support_code: str
    message: str  # short, user-facing; safe to show in a narrow panel
    hint: str  # what IT / support should check
    detail: str  # root exception summary for logs (never shown in UI)
    host: str = ""

    @property
    def user_text(self) -> str:
        return f"{self.message} ({self.support_code})"


# Signatures are matched against the lowercase concatenation of every
# exception class name and message in the chain, root cause first.
# Order matters: the first matching kind wins.
_SIGNATURES = (
    (
        FAILURE_TLS_VERIFY,
        (
            "certificate_verify_failed",
            "certificate verify failed",
            "sslcertverificationerror",
            "self signed certificate",
            "self-signed certificate",
            "unable to get local issuer",
            "certificate has expired",
            "hostname mismatch",
            "certificate is not valid for",
        ),
    ),
    (
        FAILURE_PROXY,
        (
            "proxyerror",
            "websocketproxyexception",
            "proxy authentication required",
            "tunnel connection failed",
            "failed to establish a new connection to proxy",
            "cannot connect to proxy",
            "proxy",
        ),
    ),
    (
        FAILURE_TLS_HANDSHAKE,
        (
            "wrong_version_number",
            "wrong version number",
            "sslerror",
            "ssleoferror",
            "handshake failure",
            "unexpected_eof",
            "tlsv1 alert",
            "ssl:",
        ),
    ),
    (
        FAILURE_DNS,
        (
            "gaierror",
            "getaddrinfo",
            "name or service not known",
            "nodename nor servname",
            "temporary failure in name resolution",
            "no address associated",
            "errno 11001",
            "name resolution",
            "could not resolve",
        ),
    ),
    (
        FAILURE_REFUSED,
        (
            "connectionrefused",
            "connection refused",
            "winerror 10061",
            "errno 61]",
            "errno 111]",
        ),
    ),
    (
        FAILURE_RESET,
        (
            "connectionreset",
            "connection reset",
            "remotedisconnected",
            "connection aborted",
            "winerror 10054",
            "winerror 10053",
            "errno 54]",
            "errno 104]",
        ),
    ),
    (
        FAILURE_UNREACHABLE,
        (
            "network is unreachable",
            "no route to host",
            "winerror 10051",
            "winerror 10065",
            "errno 51]",
            "errno 101]",
            "errno 113]",
        ),
    ),
    (
        FAILURE_TIMEOUT,
        (
            "timeout",
            "timed out",
        ),
    ),
)

_MESSAGES = {
    FAILURE_TLS_VERIFY: (
        "Certificate verification failed. Your network may be inspecting HTTPS traffic.",
        "A TLS-inspecting proxy or firewall is presenting a certificate Mixar does not "
        "trust. Mixar trusts the OS certificate store; make sure the organization's "
        "root CA is installed there, or point MIXAR_CA_BUNDLE (or network.ca_bundle in "
        "mixar.json) at a PEM bundle containing it. Alternatively exempt {host} from "
        "TLS inspection.",
    ),
    FAILURE_TLS_HANDSHAKE: (
        "Secure connection could not be established.",
        "The TLS handshake with {host} failed before certificate verification. "
        "'WRONG_VERSION_NUMBER' usually means a plain-HTTP proxy is answering an HTTPS "
        "request: check the proxy URL scheme and port. Otherwise a middlebox is "
        "terminating the connection.",
    ),
    FAILURE_PROXY: (
        "Proxy connection failed.",
        "The configured proxy rejected or could not tunnel the connection to {host}. "
        "Check HTTPS_PROXY / MIXAR_PROXY_URL (credentials belong in the URL). PAC files "
        "are not supported; set the proxy URL explicitly.",
    ),
    FAILURE_DNS: (
        "Could not resolve the server address.",
        "DNS lookup for {host} failed. Check DNS, split-tunnel VPN rules, or whether "
        "the domain needs to be allowlisted on an internal resolver.",
    ),
    FAILURE_TIMEOUT: (
        "Connection timed out.",
        "No response from {host}. A firewall may be silently dropping traffic on "
        "port 443, or a proxy is required but not configured.",
    ),
    FAILURE_REFUSED: (
        "Connection refused.",
        "Something on the path to {host} actively rejected the connection: usually a "
        "proxy or firewall rule, or a wrong proxy port.",
    ),
    FAILURE_RESET: (
        "Connection was closed by the network.",
        "The connection to {host} was reset mid-flight, which is typical of a firewall "
        "or TLS-inspecting proxy that blocks this destination.",
    ),
    FAILURE_UNREACHABLE: (
        "Network unreachable.",
        "No route to {host}. Check connectivity and VPN state.",
    ),
    FAILURE_UNKNOWN: (
        "Network error: {short}",
        "Unrecognized failure reaching {host}. See the log detail.",
    ),
}


def _iter_chain(exc: BaseException):
    """Yield the exception and its causes, innermost (root) first."""
    seen = []
    current = exc
    while current is not None and current not in seen:
        seen.append(current)
        current = current.__cause__ or current.__context__
    # requests / urllib wrap the original in .args / .reason without chaining.
    for item in list(seen):
        for extra in _wrapped_exceptions(item):
            if extra not in seen:
                seen.append(extra)
    return reversed(seen)


def _wrapped_exceptions(exc: BaseException):
    reason = getattr(exc, "reason", None)
    if isinstance(reason, BaseException):
        yield reason
    for arg in getattr(exc, "args", ()):
        if isinstance(arg, BaseException):
            yield arg


def _describe(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def _haystack(exc: BaseException) -> str:
    parts = []
    for item in _iter_chain(exc):
        parts.append(type(item).__name__)
        parts.append(str(item))
    return " | ".join(parts).lower()


def _host_of(url: str | None) -> str:
    if not url:
        return "the server"
    try:
        parsed = urlparse(url)
        return parsed.hostname or url
    except ValueError:
        return url


def _short(exc: BaseException, limit: int = 60) -> str:
    root = next(iter(_iter_chain(exc)), exc)
    text = str(root).strip() or type(root).__name__
    text = re.sub(r"\s+", " ", text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


# With a proxy configured the client never dials the origin, so a refused /
# unreachable / unresolved connection can only concern the proxy host.
_PROXY_STAGE_KINDS = (FAILURE_REFUSED, FAILURE_UNREACHABLE, FAILURE_DNS)


def _configured_proxy(environ=None) -> str:
    environ = os.environ if environ is None else environ
    for name in PROXY_ENV_VARS:
        value = (environ.get(name) or "").strip()
        if value:
            return value
    return ""


def classify_network_error(
    exc: BaseException,
    url: str | None = None,
    environ=None,
) -> NetworkFailure:
    """Classify ``exc`` raised while reaching ``url`` (any bundled client)."""
    host = _host_of(url)
    haystack = _haystack(exc)
    kind = FAILURE_UNKNOWN
    for candidate, needles in _SIGNATURES:
        if any(needle in haystack for needle in needles):
            kind = candidate
            break

    proxy = _configured_proxy(environ)
    if proxy and kind in _PROXY_STAGE_KINDS:
        kind = FAILURE_PROXY

    message, hint = _MESSAGES[kind]
    message = message.format(short=_short(exc))
    hint = hint.format(host=host)
    if proxy and kind not in (FAILURE_PROXY, FAILURE_UNKNOWN):
        from .proxy import redact_proxy_url

        hint += f" A proxy is configured ({redact_proxy_url(proxy)})."
    root = next(iter(_iter_chain(exc)), exc)
    detail = _describe(exc) if root is exc else f"{_describe(exc)} <- {_describe(root)}"
    return NetworkFailure(
        kind=kind,
        support_code=SUPPORT_CODES[kind],
        message=message,
        hint=hint,
        detail=detail,
        host=host,
    )


def log_network_failure(logger, failure: NetworkFailure, context: str) -> None:
    """Log at ERROR so the line survives the Prod log level.

    Includes the effective trust/proxy configuration because that is the
    first thing support needs when a customer quotes the support code.
    """
    try:
        from .setup import network_diagnostics

        diagnostics = network_diagnostics()
    except Exception:  # diagnostics must never mask the real failure
        diagnostics = {}
    logger.error(
        "%s failed [%s] %s | host=%s | %s | hint: %s | network=%s",
        context,
        failure.support_code,
        failure.message,
        failure.host,
        failure.detail,
        failure.hint,
        diagnostics,
    )
