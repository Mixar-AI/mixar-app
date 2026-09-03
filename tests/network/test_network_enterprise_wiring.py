# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Source-level pins for the enterprise network contract.

Operators are MagicMocks under pytest, so the wiring is pinned by reading
the sources (the repo's convention for operator logic).
"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "src" / "scripts"


def _read(*parts):
    return Path(REPO, *parts).read_text(encoding="utf-8")


def test_network_is_configured_before_any_bootstrap_module():
    source = _read("src", "scripts", "startup", "bootstrap", "__init__.py")
    setup = source.index("_setup_mixar_packages()\n")
    network = source.index("configure_network()")
    bootstrap = source.index("_load_bootstrap_modules()\n")
    assert setup < network < bootstrap


def test_truststore_is_a_bundled_dependency_and_verified_by_builds():
    assert "truststore>=" in _read("scripts", "python_requirements.txt")
    assert "import truststore" in _read("scripts", "unix", "build.sh")
    assert "import truststore" in _read("scripts", "windows", "build.bat")


def test_generated_config_exposes_network_keys():
    source = _read("scripts", "generate_config.py")
    for key in ('"network"', '"proxy_url"', '"ca_bundle"', '"no_proxy"'):
        assert key in source


def test_auth_transport_failures_are_classified():
    source = _read("src", "scripts", "mixar", "modules", "auth", "core", "auth.py")
    assert "Unable to connect to server" not in source
    assert source.count("classify_network_error(") >= 3
    assert source.count("log_network_failure(") >= 3


def test_sso_token_exchange_is_classified_and_stores_fenced_pair():
    source = _read("src", "scripts", "mixar", "modules", "auth", "core", "sso.py")
    assert "classify_network_error(" in source
    assert "ThreadingHTTPServer" in source
    assert "store_login_token_pair(" in source
    assert "Unable to connect to server" not in source


def test_login_operator_has_scoped_watchdog_and_keeps_failure_reason():
    source = _read(
        "src", "scripts", "mixar", "modules", "space_mixie_chat", "ui", "operators", "auth_ops.py"
    )
    assert "_release_stuck_login(attempt_id, sso_thread)" in source
    assert "SSO_LOGIN_TIMEOUT_S + _LOGIN_WATCHDOG_GRACE_S" in source
    assert 'f"Session expired. {reason}"' in source
    assert '"Session expired. Please log in again."' not in source


def test_enterprise_doc_lists_every_surface():
    doc = _read("docs", "enterprise-network.md")
    for needle in (
        "api.mixar.app",
        "www.mixar.app",
        "51731",
        "MIXAR_PROXY_URL",
        "MIXAR_CA_BUNDLE",
        "MIXAR_NO_PROXY",
        "HTTPS_PROXY",
        "NET-TLS",
        "PAC",
        "truststore",
    ):
        assert needle in doc, needle


def test_public_package_surface():
    from mixar.modules.common import network

    for name in (
        "configure_network",
        "classify_network_error",
        "log_network_failure",
        "install_trust_store",
        "configure_proxy",
        "network_diagnostics",
    ):
        assert callable(getattr(network, name))
