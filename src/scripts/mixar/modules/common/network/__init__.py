# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared network layer: OS trust store, proxy, and failure classification.

See ``docs/enterprise-network.md`` for the operator-facing contract.
"""

from .core.errors import NetworkFailure, classify_network_error, log_network_failure
from .core.proxy import ProxyReport, configure_proxy, redact_proxy_url, validate_proxy_url
from .core.setup import NetworkReport, configure_network, network_diagnostics
from .core.trust import TrustReport, get_trust_report, install_trust_store

__all__ = [
    "NetworkFailure",
    "NetworkReport",
    "ProxyReport",
    "TrustReport",
    "classify_network_error",
    "configure_network",
    "configure_proxy",
    "get_trust_report",
    "install_trust_store",
    "log_network_failure",
    "network_diagnostics",
    "redact_proxy_url",
    "validate_proxy_url",
]
