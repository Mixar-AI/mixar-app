# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Proxy resolution/export contract (modules/common/network/core/proxy.py)."""

import pytest

from mixar.modules.common.network import configure_proxy, redact_proxy_url, validate_proxy_url
from mixar.modules.common.network.core import proxy as proxy_mod


@pytest.fixture(autouse=True)
def _no_system_proxy(monkeypatch):
    monkeypatch.setattr(proxy_mod.urllib.request, "getproxies", lambda: {})


def _config(**network):
    return lambda: {"network": network}


def test_direct_when_nothing_configured():
    env = {}
    report = configure_proxy(None, env)
    assert not report.enabled and report.source == "none"
    assert "HTTPS_PROXY" not in env
    assert env["NO_PROXY"] == "localhost,127.0.0.1,::1"
    assert env["no_proxy"] == env["NO_PROXY"]


def test_mixar_env_var_wins_and_is_exported_to_every_client():
    env = {"MIXAR_PROXY_URL": "http://proxy.corp:3128", "HTTPS_PROXY": "http://old:1"}
    report = configure_proxy(_config(proxy_url="http://ignored:1"), env)
    assert report.source == "env:MIXAR_PROXY_URL"
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        assert env[name] == "http://proxy.corp:3128"


def test_config_used_when_no_mixar_env_var():
    env = {}
    report = configure_proxy(_config(proxy_url="http://proxy.corp:3128"), env)
    assert report.source == "config:network.proxy_url"
    assert env["HTTPS_PROXY"] == "http://proxy.corp:3128"


def test_standard_env_left_untouched_when_it_is_the_source():
    env = {"https_proxy": "http://ambient:8080"}
    report = configure_proxy(None, env)
    assert report.source == "env:HTTPS_PROXY"
    assert report.url == "http://ambient:8080"
    assert "HTTPS_PROXY" not in env  # we did not rewrite the ambient variables


def test_system_proxy_is_exported_so_websocket_client_sees_it(monkeypatch):
    monkeypatch.setattr(proxy_mod.urllib.request, "getproxies", lambda: {"https": "http://sys.corp:9"})
    env = {}
    report = configure_proxy(None, env)
    assert report.source == "system"
    assert env["https_proxy"] == "http://sys.corp:9"


def test_credentials_are_redacted_in_report():
    env = {"MIXAR_PROXY_URL": "http://alice:hunter2@proxy.corp:3128"}
    report = configure_proxy(None, env)
    assert report.url == "http://alice:***@proxy.corp:3128"
    assert env["HTTPS_PROXY"] == "http://alice:hunter2@proxy.corp:3128"  # clients still get the real one


@pytest.mark.parametrize(
    "url, fragment",
    [
        ("socks5://proxy.corp:1080", "not supported"),
        ("proxy.corp:3128", "must start with http"),
        ("http://", "no host"),
    ],
)
def test_invalid_proxy_is_ignored_with_error(url, fragment):
    env = {"MIXAR_PROXY_URL": url}
    report = configure_proxy(None, env)
    assert not report.enabled
    assert fragment in report.error
    assert "HTTPS_PROXY" not in env


def test_no_proxy_merges_all_sources_and_always_keeps_loopback():
    env = {"NO_PROXY": "internal.corp, 10.0.0.0/8", "MIXAR_NO_PROXY": "cdn.corp"}
    configure_proxy(_config(no_proxy="git.corp"), env)
    assert env["NO_PROXY"] == "cdn.corp,git.corp,internal.corp,10.0.0.0/8,localhost,127.0.0.1,::1"


def test_validate_and_redact_helpers():
    assert validate_proxy_url("https://proxy.corp:443") is None
    assert redact_proxy_url("http://proxy.corp:3128") == "http://proxy.corp:3128"
    assert redact_proxy_url("http://bob:pw@proxy.corp") == "http://bob:***@proxy.corp"
