# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Persisted telemetry consent preference."""

from mixar.config.config import add_config, get_config


def is_enabled() -> bool:
    """Usage analytics is enabled unless the user has explicitly opted out."""
    return bool(get_config().get("share_usage_data", True))


def set_enabled(enabled: bool) -> bool:
    client = None
    saved = add_config("share_usage_data", bool(enabled))
    # Agent commands no longer have per-request HTTP consent headers.
    try:
        from mixar.modules.space_mixie_chat.core.jsonrpc_client import get_jsonrpc_client
        client = get_jsonrpc_client()
        if client and client.is_connected:
            def acknowledged(result):
                if isinstance(result, dict) and result.get('code'):
                    # Reconnect carries the new consent in the handshake.
                    if client._ws:
                        client._ws.close()
            client.send_request('system.set_context', {'telemetry_consent': bool(enabled)},
                                on_result=acknowledged)
    except Exception:
        from mixar.config.logging_config import get_logger
        get_logger(__name__).debug('Consent update waits for the next agent connection')
        if client and client.is_connected and client._ws:
            import threading
            threading.Thread(target=client._ws.close, daemon=True).start()
    return saved
