# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Account-token forwarding and uncertain mutation recovery."""

from types import SimpleNamespace
from unittest.mock import Mock
import sys

import pytest
import requests

from mixar.modules.mcp_bridge.core import forward
from mixar.modules.common import network
from mixar.modules.common.usage.core import poller


@pytest.fixture
def dependencies(monkeypatch):
    tokens = Mock(return_value="private-account-token")
    refresh = Mock(return_value={"success": True})
    usage_refresh = Mock()
    post = Mock()
    monkeypatch.setitem(sys.modules, "mixar.modules.auth.core.auth", SimpleNamespace(
        get_access_token=tokens, refresh_access_token=refresh))
    monkeypatch.setattr(poller, "request_refresh", usage_refresh)
    monkeypatch.setattr(forward.requests, "post", post)
    return SimpleNamespace(tokens=tokens, refresh=refresh, post=post, usage_refresh=usage_refresh)


CONTEXT = {"headers": {"X-Client-Version": "1.2.3", "x-telemetry-consent": "0"},
           "backend_url": "https://api.example.test", "instance_id": "instance",
           "session_id": "scene"}
REQUEST = {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "execute_bpy_script"}}


def response(status, body=None):
    return SimpleNamespace(status_code=status, json=lambda: body)


def test_reuses_desktop_auth_and_context_without_returning_token(dependencies):
    dependencies.post.return_value = response(200, {"jsonrpc": "2.0", "id": 7, "result": {"content": []}})
    status, body = forward.forward(REQUEST, CONTEXT, {"X-Mixar-Call-Id": "stable"})
    assert status == 200 and "private-account-token" not in str(body)
    args = dependencies.post.call_args.kwargs
    assert args["headers"]["Authorization"] == "Bearer private-account-token"
    assert args["headers"]["X-Mixar-Session-Id"] == "scene"
    assert args["headers"]["x-telemetry-consent"] == "0"
    assert args["allow_redirects"] is False
    assert args["headers"]["X-Mixar-Call-Id"] == "stable"
    dependencies.usage_refresh.assert_called_once()


def test_only_explicit_unauthorized_response_can_retry_with_same_call_id(dependencies):
    dependencies.post.side_effect = [response(401), response(200, {"result": {}})]
    assert forward.forward(REQUEST, CONTEXT, {"X-Mixar-Call-Id": "stable"})[0] == 200
    assert dependencies.post.call_count == 2
    assert all(call.kwargs["headers"]["X-Mixar-Call-Id"] == "stable" for call in dependencies.post.call_args_list)
    dependencies.refresh.assert_called_once()


def test_timeout_never_retries_and_refreshes_authoritative_balance(dependencies, monkeypatch):
    dependencies.post.side_effect = requests.exceptions.Timeout("timed out")
    monkeypatch.setattr(network, "classify_network_error", lambda exc: SimpleNamespace(support_code="NET-TIMEOUT"))
    monkeypatch.setattr(network, "log_network_failure", Mock())
    status, body = forward.forward(REQUEST, CONTEXT, {"X-Mixar-Call-Id": "stable"})
    assert status == 502 and "NET-TIMEOUT" in body["error"]
    dependencies.post.assert_called_once()
    dependencies.refresh.assert_not_called()
    dependencies.usage_refresh.assert_called_once()


def test_unavailable_endpoint_has_actionable_message_and_no_retry(dependencies):
    dependencies.post.return_value = response(404)
    status, body = forward.forward(REQUEST, CONTEXT, {})
    assert status == 404 and "does not have Mixar MCP" in body["error"]
    dependencies.post.assert_called_once()
