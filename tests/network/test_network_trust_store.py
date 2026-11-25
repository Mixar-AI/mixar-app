# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Trust-store selection contract (modules/common/network/core/trust.py).

``truststore`` is replaced by a recording stub so the test process's
``ssl.SSLContext`` is never patched.
"""

import os
import ssl
import sys
import types
from unittest import mock

import pytest

from mixar.modules.common.network import install_trust_store
from mixar.modules.common.network.constants import (
    CA_BUNDLE_ENV_VARS,
    ENV_CA_BUNDLE,
    ENV_EXTRA_CA_CERTS,
    SSL_KEYLOG_ENV_VAR,
    TRUST_MODE_BUNDLE,
    TRUST_MODE_CERTIFI,
    TRUST_MODE_OS,
)
from mixar.modules.common.network.core import trust as trust_mod


@pytest.fixture
def fake_truststore(monkeypatch):
    calls = []
    module = types.ModuleType("truststore")
    module.inject_into_ssl = lambda: calls.append("inject")
    monkeypatch.setitem(sys.modules, "truststore", module)
    monkeypatch.setattr(trust_mod, "_report", None)
    return calls


@pytest.fixture
def no_truststore(monkeypatch):
    monkeypatch.setitem(sys.modules, "truststore", None)  # import raises ImportError
    monkeypatch.setattr(trust_mod, "_report", None)


@pytest.fixture
def not_linux(monkeypatch):
    monkeypatch.setattr(trust_mod.sys, "platform", "darwin")


def test_os_trust_store_is_default(fake_truststore, not_linux):
    env = {}
    report = install_trust_store(None, env, force=True)
    assert report.mode == TRUST_MODE_OS
    assert fake_truststore == ["inject"]
    assert not any(name in env for name in CA_BUNDLE_ENV_VARS)


def test_install_is_idempotent(fake_truststore, not_linux):
    first = install_trust_store(None, {}, force=True)
    second = install_trust_store(None, {})
    assert second is first
    assert fake_truststore == ["inject"]


def test_custom_bundle_from_mixar_env_replaces_os_store(fake_truststore, not_linux, tmp_path):
    bundle = tmp_path / "corp-root.pem"
    bundle.write_text("-----BEGIN CERTIFICATE-----\n")
    env = {"MIXAR_CA_BUNDLE": str(bundle)}
    report = install_trust_store(lambda: {"network": {"ca_bundle": "/ignored.pem"}}, env, force=True)
    assert report.mode == TRUST_MODE_BUNDLE
    assert report.source == "env:MIXAR_CA_BUNDLE"
    assert fake_truststore == []  # explicit bundle => plain OpenSSL verification
    for name in CA_BUNDLE_ENV_VARS:
        assert env[name] == str(bundle)


def test_custom_bundle_from_config(fake_truststore, not_linux, tmp_path):
    bundle = tmp_path / "corp-root.pem"
    bundle.write_text("x")
    env = {}
    report = install_trust_store(lambda: {"network": {"ca_bundle": str(bundle)}}, env, force=True)
    assert report.mode == TRUST_MODE_BUNDLE
    assert report.source == "config:network.ca_bundle"
    assert env["REQUESTS_CA_BUNDLE"] == str(bundle)


def test_preexisting_requests_ca_bundle_is_honored_everywhere(fake_truststore, not_linux, tmp_path):
    bundle = tmp_path / "it.pem"
    bundle.write_text("x")
    env = {"REQUESTS_CA_BUNDLE": str(bundle)}
    report = install_trust_store(None, env, force=True)
    assert report.mode == TRUST_MODE_BUNDLE
    assert env["SSL_CERT_FILE"] == str(bundle)
    assert env["WEBSOCKET_CLIENT_CA_BUNDLE"] == str(bundle)


def test_missing_bundle_falls_back_to_os_store_and_reports_error(fake_truststore, not_linux):
    env = {"MIXAR_CA_BUNDLE": "/nonexistent/corp.pem"}
    report = install_trust_store(None, env, force=True)
    assert report.mode == TRUST_MODE_OS
    assert "missing file" in report.error
    assert fake_truststore == ["inject"]
    assert "SSL_CERT_FILE" not in env


def test_without_truststore_certifi_is_reported(no_truststore, not_linux, monkeypatch):
    monkeypatch.setattr(trust_mod, "_certifi_path", lambda: "/pkg/certifi/cacert.pem")
    report = install_trust_store(None, {}, force=True)
    assert report.mode == TRUST_MODE_CERTIFI
    assert report.bundle_path == "/pkg/certifi/cacert.pem"
    assert report.error


def test_linux_without_system_bundle_points_openssl_at_certifi(fake_truststore, monkeypatch):
    monkeypatch.setattr(trust_mod.sys, "platform", "linux")
    monkeypatch.setattr(trust_mod, "_linux_system_ca_available", lambda: False)
    monkeypatch.setattr(trust_mod, "_certifi_path", lambda: "/pkg/certifi/cacert.pem")
    env = {}
    report = install_trust_store(None, env, force=True)
    assert report.mode == TRUST_MODE_CERTIFI
    assert env["SSL_CERT_FILE"] == "/pkg/certifi/cacert.pem"
    assert fake_truststore == ["inject"]


def test_linux_with_system_bundle_uses_os_store(fake_truststore, monkeypatch):
    monkeypatch.setattr(trust_mod.sys, "platform", "linux")
    monkeypatch.setattr(trust_mod, "_linux_system_ca_available", lambda: True)
    env = {}
    report = install_trust_store(None, env, force=True)
    assert report.mode == TRUST_MODE_OS
    assert "SSL_CERT_FILE" not in env


def test_ssl_key_log_file_is_dropped_with_a_warning(fake_truststore, not_linux, monkeypatch):
    log = mock.Mock()
    monkeypatch.setattr(trust_mod, "logger", log)
    env = {SSL_KEYLOG_ENV_VAR: "/keys.log"}
    install_trust_store(None, env, force=True, search_dirs=())
    assert SSL_KEYLOG_ENV_VAR not in env
    log.warning.assert_called_once()

    log.reset_mock()
    install_trust_store(None, {}, force=True, search_dirs=())
    log.warning.assert_not_called()

    env = {SSL_KEYLOG_ENV_VAR: ""}  # set but empty: clients skip it, so no warning
    install_trust_store(None, env, force=True, search_dirs=())
    assert SSL_KEYLOG_ENV_VAR not in env
    log.warning.assert_not_called()


@pytest.mark.skipif(sys.platform.startswith("win"), reason="chmod 000 does not deny reads on Windows")
def test_unopenable_ssl_key_log_file_cannot_break_tls_contexts(fake_truststore, not_linux, monkeypatch, tmp_path):
    # Mixar-AI/mixar-backend#1879: urllib3 opens SSLKEYLOGFILE on every context,
    # so an unopenable path made ``import requests`` raise PermissionError.
    urllib3_ssl = pytest.importorskip("urllib3.util.ssl_")
    if os.geteuid() == 0:
        pytest.skip("root can open a chmod 000 file")
    # Runs against the real os.environ: hand every variable install_trust_store
    # reads or exports to monkeypatch so a runner's own CA settings can't leak.
    for name in (*CA_BUNDLE_ENV_VARS, ENV_CA_BUNDLE, ENV_EXTRA_CA_CERTS):
        monkeypatch.delenv(name, raising=False)
    key_log = tmp_path / "virtual_file.log"
    key_log.write_text("")
    key_log.chmod(0)
    monkeypatch.setenv(SSL_KEYLOG_ENV_VAR, str(key_log))
    original_class, original_new = ssl.SSLContext, ssl.SSLContext.__new__
    try:
        install_trust_store(None, force=True, search_dirs=())
        urllib3_ssl.create_urllib3_context()
        assert SSL_KEYLOG_ENV_VAR not in os.environ
    finally:
        trust_mod._uninstall_extra_certs()
        key_log.chmod(0o600)
    assert ssl.SSLContext is original_class
    assert ssl.SSLContext.__new__ is original_new
