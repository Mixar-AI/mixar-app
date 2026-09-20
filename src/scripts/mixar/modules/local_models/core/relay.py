# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Client-side executor for the backend's ``llm.request`` relay contract.

The backend's LOCAL provider cannot reach the user's machine, so it sends
an ``llm.request`` JSON-RPC request down the agent WebSocket; this module
performs that HTTP call against the *local* model server and hands the
raw response back. Trust model: the backend validates the target it asks
for, and this client INDEPENDENTLY re-validates on its own network —
neither side trusts the other blindly:

- method must be POST;
- only http(s) URLs whose host is loopback, RFC1918-private, or IPv6 ULA
  (every DNS answer must qualify — a name with any public answer is
  refused, which also blocks 169.254.169.254-style metadata targets since
  link-local is deliberately NOT allowed);
- the (scheme, host, port, path) must exactly match one currently
  APPROVED base — the managed server from the manifest, plus an optional
  custom base the user approved at save time (``set_approved_bases``);
  the only path ever allowed is the derived ``/v1/chat/completions``;
- request and response byte caps; header allowlists both ways;
- redirects are never followed (a 3xx passes through as a plain non-2xx
  result with Location stripped), and DNS-name targets are pinned to the
  address that passed the allowlist so connect-time re-resolution cannot
  be rebound (https + DNS name is refused outright — TLS can't be pinned
  to an IP without breaking certificate verification).

Results: ``respond()`` is called exactly once with either

- success (any HTTP status, non-2xx passes through for the backend SDK):
  ``{"status_code": int, "headers": {allowlisted}, "body": str}``
- an error marker the caller translates to a JSON-RPC error:
  ``{"error": {"code": str, "message": str}}``

Pure stdlib + fully synchronous — callers run it on a worker thread. No
bpy imports. ``_urlopen`` / ``_getaddrinfo`` are test seams.
"""

import ipaddress
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Iterable, Optional, Tuple

from mixar.config.logging_config import get_logger

from ..constants import (
    LOG_PREFIX,
    MAX_RELAY_REQUEST_BYTES,
    MAX_RELAY_RESPONSE_BYTES,
    RELAY_ALLOWED_REQUEST_HEADERS,
    RELAY_ALLOWED_RESPONSE_HEADERS,
    RELAY_CHAT_COMPLETIONS_PATH,
    RELAY_TIMEOUT_S,
)

logger = get_logger(__name__)

class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """Turn every 3xx into an HTTPError instead of following it.

    A local server must never be able to bounce the relay to another
    target (metadata IPs, public hosts) — the redirect status passes
    through to the backend as an ordinary non-2xx result, with Location
    stripped by the response-header allowlist.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


# Test seams. The opener never follows redirects (see _RefuseRedirects).
_urlopen = urllib.request.build_opener(_RefuseRedirects()).open
_getaddrinfo = socket.getaddrinfo

_lock = threading.Lock()
_approved: Tuple[dict, ...] = ()

_RFC1918 = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)
_IPV6_ULA = ipaddress.ip_network("fc00::/7")


def _error(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


# ---------------------------------------------------------------------------
# Approved bases
# ---------------------------------------------------------------------------

def _parse_base(base_url: str) -> Optional[dict]:
    try:
        parts = urllib.parse.urlsplit(base_url.strip())
        # .hostname/.port raise ValueError on malformed netloc (bad port,
        # bad IPv6 bracketing) — treat as "not a valid base", never raise.
        hostname, port = parts.hostname, parts.port
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not hostname:
        return None
    path = (parts.path or "").rstrip("/")
    if path.endswith("/v1"):
        derived = path + "/chat/completions"
    else:
        derived = path + RELAY_CHAT_COMPLETIONS_PATH
    return {
        "scheme": parts.scheme.lower(),
        "host": hostname.lower(),
        "port": port or (443 if parts.scheme.lower() == "https" else 80),
        "path": derived,
    }


def set_approved_bases(base_urls: Iterable[str]) -> None:
    """Replace the approved-base set (managed server base + optional
    user-approved custom base). Malformed entries are dropped."""
    global _approved
    parsed = tuple(
        base for base in (_parse_base(url) for url in base_urls)
        if base is not None
    )
    with _lock:
        _approved = parsed
    logger.debug("%s relay approved bases: %s", LOG_PREFIX, parsed)


def validate_base_url(base_url: str) -> Optional[str]:
    """Sanity-check a user-entered base URL for local relaying.

    Returns a UI-safe error string, or None when the base parses and its
    host is loopback / RFC1918 / IPv6 ULA (same rule the relay enforces at
    request time — checking here means the save dialog refuses early with a
    clear message instead of every later request being denied).
    """
    base = _parse_base(base_url or "")
    if base is None:
        return "Enter a valid http(s) URL, e.g. http://127.0.0.1:11434"
    if not _host_allowed(base["host"], base["port"]):
        return "Only servers on this computer or your local network are allowed"
    return None


def get_approved_bases() -> Tuple[str, ...]:
    """The currently approved request URLs (fully derived)."""
    with _lock:
        return tuple(
            f"{b['scheme']}://{b['host']}:{b['port']}{b['path']}"
            for b in _approved
        )


def _match_approved(scheme: str, host: str, port: int, path: str) -> bool:
    with _lock:
        approved = _approved
    return any(
        base["scheme"] == scheme and base["host"] == host
        and base["port"] == port and base["path"] == path
        for base in approved
    )


# ---------------------------------------------------------------------------
# Host allowlist
# ---------------------------------------------------------------------------

def _addr_allowed(address: str) -> bool:
    """Loopback, RFC1918, or IPv6 ULA. Link-local is deliberately NOT
    allowed (blocks 169.254.169.254-style metadata endpoints)."""
    try:
        ip = ipaddress.ip_address(address.split("%")[0])
    except ValueError:
        return False
    if ip.is_loopback:
        return True
    if isinstance(ip, ipaddress.IPv6Address):
        mapped = ip.ipv4_mapped
        if mapped is not None:
            return _addr_allowed(str(mapped))
        return ip in _IPV6_ULA
    return any(ip in network for network in _RFC1918)


def _resolve_allowed(host: str, port: int) -> Optional[str]:
    """Return a connectable local address for ``host``, or None if denied.

    IP literals are checked directly and returned as-is. DNS names must
    resolve with EVERY answer loopback/private/ULA; the first answer is
    returned so the caller can PIN the connection to the address that was
    validated (re-resolving at connect time would reopen a DNS-rebinding
    window between check and use).
    """
    try:
        ipaddress.ip_address(host)
        return host if _addr_allowed(host) else None
    except ValueError:
        pass
    try:
        answers = _getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        return None
    if not answers:
        return None
    if not all(_addr_allowed(info[4][0]) for info in answers):
        return None
    return str(answers[0][4][0])


def _host_allowed(host: str, port: int) -> bool:
    return _resolve_allowed(host, port) is not None


# ---------------------------------------------------------------------------
# Request execution
# ---------------------------------------------------------------------------

def _filter_request_headers(headers) -> dict:
    if not isinstance(headers, dict):
        return {}
    return {
        str(key): str(value) for key, value in headers.items()
        if str(key).lower() in RELAY_ALLOWED_REQUEST_HEADERS
    }


def _filter_response_headers(headers) -> dict:
    filtered = {}
    try:
        items = headers.items()
    except Exception:
        return filtered
    for key, value in items:
        lowered = str(key).lower()
        if lowered in RELAY_ALLOWED_RESPONSE_HEADERS:
            filtered[lowered] = str(value)
    return filtered


def _read_bounded(response) -> Optional[bytes]:
    """Response body up to the cap; None means the cap was exceeded."""
    body = response.read(MAX_RELAY_RESPONSE_BYTES + 1)
    if len(body) > MAX_RELAY_RESPONSE_BYTES:
        return None
    return body


def _validate(params: dict) -> Tuple[Optional[dict], Optional[str], Optional[str]]:
    """Validate one relay request.

    Returns ``(error_marker, pinned_url, host_header)``. On success the
    error marker is None and ``pinned_url`` is the URL to actually fetch —
    rebuilt from the validated parts (never the raw input, so userinfo/
    query/fragment can't ride along) and, for DNS-name hosts, pinned to
    the address that passed the allowlist so connect-time re-resolution
    can't be rebound to a public address. ``host_header`` carries the
    original name for the server's virtual-host routing in that case.
    """
    method = str(params.get("method") or "").upper()
    if method != "POST":
        return _error("relay_denied", f"method not allowed: {method or '<none>'}"), None, None
    url = params.get("url")
    if not isinstance(url, str) or not url:
        return _error("relay_denied", "missing url"), None, None
    try:
        parts = urllib.parse.urlsplit(url)
        hostname, explicit_port = parts.hostname, parts.port
    except ValueError:
        return _error("relay_denied", "malformed url"), None, None
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        return _error("relay_denied", f"scheme not allowed: {scheme!r}"), None, None
    if parts.query or parts.fragment or parts.username is not None:
        return _error("relay_denied", "url must not carry query/fragment/userinfo"), None, None
    host = (hostname or "").lower()
    if not host:
        return _error("relay_denied", "missing host"), None, None
    port = explicit_port or (443 if scheme == "https" else 80)
    pinned = _resolve_allowed(host, port)
    if pinned is None:
        return _error("relay_denied", "host is not a local/private address"), None, None
    if not _match_approved(scheme, host, port, parts.path or ""):
        return _error("relay_denied", "target is not an approved local base"), None, None
    if pinned == host:
        netloc = f"[{host}]" if ":" in host else host
        return None, urllib.parse.urlunsplit(
            (scheme, f"{netloc}:{port}", parts.path or "", "", "")
        ), None
    # DNS name that resolved local. TLS verifies the certificate against the
    # URL's hostname, so an https connection can't be pinned to an IP here —
    # refuse rather than leave the rebinding window open.
    if scheme == "https":
        return _error(
            "relay_denied",
            "https with a DNS-name host is not supported — use an IP literal",
        ), None, None
    netloc = f"[{pinned}]" if ":" in pinned else pinned
    pinned_url = urllib.parse.urlunsplit(
        (scheme, f"{netloc}:{port}", parts.path or "", "", "")
    )
    host_header = host if explicit_port is None else f"{host}:{explicit_port}"
    return None, pinned_url, host_header


def handle_llm_request(params: dict, respond: Callable[[dict], None]) -> None:
    """Execute one ``llm.request`` against a local model server.

    ``params``: ``{"method": "POST", "url": str, "headers": dict,
    "body": str|bytes}``. Calls ``respond`` exactly once (see module
    docstring for both result shapes). Blocking — run on a worker thread.
    """
    denial, pinned_url, host_header = _validate(params)
    if denial is not None:
        logger.warning("%s relay refused: %s", LOG_PREFIX,
                       denial["error"]["message"])
        respond(denial)
        return

    body = params.get("body")
    if isinstance(body, str):
        body = body.encode("utf-8")
    elif body is None:
        body = b""
    elif not isinstance(body, (bytes, bytearray)):
        respond(_error("relay_denied", "body must be a string"))
        return
    if len(body) > MAX_RELAY_REQUEST_BYTES:
        respond(_error("relay_request_too_large",
                       f"request body exceeds {MAX_RELAY_REQUEST_BYTES} bytes"))
        return

    headers = _filter_request_headers(params.get("headers"))
    if host_header:
        # Connection is pinned to the resolved IP; keep the original name
        # for the local server's virtual-host routing.
        headers["Host"] = host_header
    request = urllib.request.Request(
        pinned_url,
        data=bytes(body),
        headers=headers,
        method="POST",
    )
    try:
        response = _urlopen(request, timeout=RELAY_TIMEOUT_S)
    except urllib.error.HTTPError as http_error:
        # Non-2xx passes through as a normal result — the backend SDK
        # understands provider error statuses (429, 400, ...).
        response = http_error
    except Exception as exc:
        logger.warning("%s relay transport failure: %s", LOG_PREFIX, exc)
        respond(_error("relay_transport", f"local server unreachable: {exc}"))
        return

    try:
        raw = _read_bounded(response)
        status = getattr(response, "status", None)
        if status is None:
            status = response.getcode()
        headers = _filter_response_headers(response.headers)
    except Exception as exc:
        respond(_error("relay_transport", f"error reading response: {exc}"))
        return
    finally:
        try:
            response.close()
        except Exception:
            pass

    if raw is None:
        respond(_error("relay_response_too_large",
                       f"response exceeds {MAX_RELAY_RESPONSE_BYTES} bytes"))
        return
    respond({
        "status_code": int(status),
        "headers": headers,
        "body": raw.decode("utf-8", errors="replace"),
    })
