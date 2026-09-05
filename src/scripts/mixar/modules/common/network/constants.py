# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Constants for the shared network layer (trust store, proxy, error taxonomy)."""

# --- Failure taxonomy -------------------------------------------------------
# Every outbound failure is reduced to one of these kinds. The support code is
# shown next to the user-facing message so a customer can quote it verbatim.
FAILURE_TLS_VERIFY = "tls_verify"
FAILURE_TLS_HANDSHAKE = "tls_handshake"
FAILURE_PROXY = "proxy"
FAILURE_DNS = "dns"
FAILURE_TIMEOUT = "timeout"
FAILURE_REFUSED = "refused"
FAILURE_RESET = "reset"
FAILURE_UNREACHABLE = "unreachable"
FAILURE_UNKNOWN = "unknown"

SUPPORT_CODES = {
    FAILURE_TLS_VERIFY: "NET-TLS",
    FAILURE_TLS_HANDSHAKE: "NET-TLS2",
    FAILURE_PROXY: "NET-PROXY",
    FAILURE_DNS: "NET-DNS",
    FAILURE_TIMEOUT: "NET-TIMEOUT",
    FAILURE_REFUSED: "NET-REFUSED",
    FAILURE_RESET: "NET-RESET",
    FAILURE_UNREACHABLE: "NET-UNREACH",
    FAILURE_UNKNOWN: "NET-UNKNOWN",
}

# --- Mixar-specific configuration surface -----------------------------------
# Environment variables win over mixar.json so MDM / login scripts can set
# them fleet-wide without editing the install.
ENV_CA_BUNDLE = "MIXAR_CA_BUNDLE"
ENV_PROXY_URL = "MIXAR_PROXY_URL"
ENV_NO_PROXY = "MIXAR_NO_PROXY"

CONFIG_SECTION = "network"
CONFIG_CA_BUNDLE = "ca_bundle"
CONFIG_PROXY_URL = "proxy_url"
CONFIG_NO_PROXY = "no_proxy"

# --- Standard variables honored by the bundled HTTP/WebSocket clients -------
# requests reads REQUESTS_CA_BUNDLE; httpx, urllib and http.client read
# SSL_CERT_FILE (via OpenSSL); websocket-client reads its own variable.
# A custom bundle is exported to all three so every client agrees.
CA_BUNDLE_ENV_VARS = (
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
    "WEBSOCKET_CLIENT_CA_BUNDLE",
)
# Standard pre-existing overrides, checked (in this order) when no Mixar
# variable is set.
STANDARD_CA_BUNDLE_ENV_VARS = ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE")

PROXY_ENV_VARS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")
NO_PROXY_ENV_VARS = ("NO_PROXY", "no_proxy")
SUPPORTED_PROXY_SCHEMES = ("http", "https")
# SOCKS needs PySocks / python-socks, which are not bundled.
UNSUPPORTED_PROXY_SCHEMES = ("socks4", "socks4a", "socks5", "socks5h")

# The SSO callback server and local model relays live on loopback; a proxy
# must never be asked to reach them.
LOOPBACK_NO_PROXY = ("localhost", "127.0.0.1", "::1")

# --- Trust modes (reported in logs and diagnostics) ---------------------------
TRUST_MODE_OS = "os-trust-store"
TRUST_MODE_BUNDLE = "custom-bundle"
TRUST_MODE_CERTIFI = "certifi-fallback"

# Where Linux distributions keep the system CA bundle. Mirrors the list
# truststore searches, so the fallback decision matches what it will do.
LINUX_CA_FILE_CANDIDATES = (
    "/etc/ssl/cert.pem",
    "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem",
    "/etc/pki/tls/cert.pem",
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/ssl/ca-bundle.pem",
)

ENTERPRISE_DOC_PATH = "docs/enterprise-network.md"
