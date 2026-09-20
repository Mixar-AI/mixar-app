# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared network layer: OS trust store, proxy, and failure classification.

See ``docs/enterprise-network.md`` for the operator-facing contract.
"""

from .core.errors import NetworkFailure, classify_network_error, log_network_failure
from .core.proxy import ProxyReport, configure_proxy, redact_proxy_url, validate_proxy_url
from .core.setup import NetworkReport, configure_network, network_diagnostics
from .core.trust import (
    ExtraCerts,
    TrustReport,
    collect_extra_ca_certs,
    get_trust_report,
    install_trust_store,
    user_certs_dir,
)

__all__ = [
    "ExtraCerts",
    "NetworkFailure",
    "NetworkReport",
    "ProxyReport",
    "TrustReport",
    "classify_network_error",
    "collect_extra_ca_certs",
    "configure_network",
    "configure_proxy",
    "get_trust_report",
    "install_trust_store",
    "log_network_failure",
    "network_diagnostics",
    "redact_proxy_url",
    "user_certs_dir",
    "validate_proxy_url",
]
