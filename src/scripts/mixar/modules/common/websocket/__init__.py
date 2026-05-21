# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Reusable WebSocket infrastructure for Mixar modules.

This package provides thread-safe WebSocket communication components
that can be used by any module requiring real-time server communication.

Usage:
    from mixar.modules.common.websocket import (
        WebSocketClient,
        create_websocket_client,
        get_websocket_client,
        cleanup_websocket_client,
        Message,
        MessageType,
        get_message_queues,
    )

    # Create and connect
    client = create_websocket_client(
        url="ws://localhost:8000/agent/ws",
        instance_id="my-instance-id",
    )
    client.connect()

    # Send messages
    client.send(Message(
        type=MessageType.PING,
        instance_id=client.instance_id,
    ))

    # Receive messages (typically in a timer callback)
    queues = get_message_queues()
    message = queues.receive()
    if message:
        handle_message(message)
"""

from .client import (
    WebSocketClient,
    cleanup_websocket_client,
    create_websocket_client,
    get_websocket_client,
)
from .message_queue import MessageQueues, get_message_queues
from .protocol import (
    Message,
    MessageType,
    create_ping_message,
    deserialize_message,
    register_message_type,
    serialize_message,
)

__all__ = [
    # Client
    "WebSocketClient",
    "create_websocket_client",
    "get_websocket_client",
    "cleanup_websocket_client",
    # Queues
    "MessageQueues",
    "get_message_queues",
    # Protocol
    "Message",
    "MessageType",
    "serialize_message",
    "deserialize_message",
    "create_ping_message",
    "register_message_type",
]
