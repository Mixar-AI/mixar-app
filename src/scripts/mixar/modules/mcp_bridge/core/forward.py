# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Authenticated backend forwarding, using Mixar's process-wide trust/proxy."""

import requests

from mixar.config.logging_config import get_logger

_logger = get_logger(__name__)


def forward(request, context, extra_headers):
    from mixar.modules.auth.core.auth import get_access_token, refresh_access_token
    from mixar.modules.common.network import classify_network_error, log_network_failure

    token = get_access_token()
    if not token:
        return 401, {"error": "Sign in to Mixar before connecting an AI client"}
    headers = {
        **context["headers"], **extra_headers,
        "Authorization": "Bearer " + token,
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "X-Mixar-Instance-Id": context["instance_id"],
        "X-Mixar-Session-Id": context["session_id"],
    }
    try:
        for attempt in range(2):
            # No automatic transport retries: the mutation may already have run.
            response = requests.post(context["backend_url"].rstrip("/") + "/api/v1/mcp",
                                     json=request, headers=headers, timeout=(10, 600),
                                     allow_redirects=False)
            if response.status_code == 401 and attempt == 0:
                if refresh_access_token().get("success"):
                    headers["Authorization"] = "Bearer " + get_access_token()
                    continue
            break
        if response.status_code == 202:
            return 202, None
        if 200 <= response.status_code < 300:
            return response.status_code, response.json()
        messages = {
            401: "Your Mixar session expired; sign in again",
            403: "This Mixar account cannot access the requested scene",
            404: "This backend does not have Mixar MCP yet",
            426: "Update Mixar before using MCP",
            429: "Too many MCP requests; try again shortly",
        }
        return response.status_code, {"error": messages.get(
            response.status_code, "Mixar MCP returned HTTP %d" % response.status_code)}
    except requests.exceptions.RequestException as exc:
        failure = classify_network_error(exc)
        log_network_failure(_logger, failure, context="mcp_relay")
        return 502, {"error": "MCP network request failed (%s); reconnect using the same call ID" % failure.support_code}
    finally:
        if request.get("method") == "tools/call":
            # The poller's flag is thread-safe; only its main-thread timer
            # updates the account card. Fetch authoritatively even on timeout.
            try:
                from mixar.modules.common.usage.core.poller import request_refresh
                request_refresh()
            except Exception:
                _logger.debug("MCP usage refresh deferred to the regular poll")
