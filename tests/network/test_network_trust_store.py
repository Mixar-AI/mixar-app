# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Trust-store selection contract (modules/common/network/core/trust.py).

``truststore`` is replaced by a recording stub so the test process's
``ssl.SSLContext`` is never patched.
"""

import sys
import types

import pytest

from mixar.modules.common.network import install_trust_store
from mixar.modules.common.network.constants import (
    CA_BUNDLE_ENV_VARS,
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
