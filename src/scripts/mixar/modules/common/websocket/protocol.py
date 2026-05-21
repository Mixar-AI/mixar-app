# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Base WebSocket message protocol definitions.

Provides extensible message types and serialization for WebSocket communication.
Modules can extend MessageType with their own types.
"""

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class SafeJSONEncoder(json.JSONEncoder):
    """
    JSON encoder that handles non-serializable objects safely.

    Converts bpy objects and other non-serializable types to string
    representations to prevent crashes during serialization.
    """

    def default(self, obj: Any) -> Any:
        # Check for bpy types (have bl_rna attribute)
        if hasattr(obj, "bl_rna"):
            name = getattr(obj, "name", None)
            if name:
                return f"<{type(obj).__name__}: {name}>"
            return f"<{type(obj).__name__}>"
        # Try parent class default, fall back to string
        try:
            return super().default(obj)
        except TypeError:
            return str(obj)


class MessageType(Enum):
    """
    Base message types for WebSocket communication.

    Modules can use these directly or define their own extensions.
    """
    # Connection events
    CONNECTED = "connection_established"
    DISCONNECTED = "disconnected"
    PING = "ping"
    PONG = "pong"
    ERROR = "error"


# Mapping from server event types to MessageType
SERVER_EVENT_TYPES: dict[str, MessageType] = {
    "connection_established": MessageType.CONNECTED,
    "pong": MessageType.PONG,
    "error": MessageType.ERROR,
}


def register_message_type(event_type: str, msg_type: MessageType) -> None:
    """
    Register a custom message type mapping.

    Allows modules to extend the protocol with their own message types.

    Args:
        event_type: Server event type string
        msg_type: MessageType enum value to map to
    """
    SERVER_EVENT_TYPES[event_type] = msg_type


@dataclass
class Message:
    """WebSocket message container."""

    type: MessageType
    payload: dict = field(default_factory=dict)
    session_id: str = ""
    instance_id: str = ""
    timestamp: float = field(default_factory=time.time)


def serialize_message(msg: Message) -> str:
    """
    Serialize a Message to JSON string for sending.

    Uses SafeJSONEncoder to handle any non-serializable objects
    (like bpy objects) that might accidentally end up in the payload.

    Args:
        msg: Message to serialize

    Returns:
        JSON string
    """
    data = {
        "action": msg.type.value,
        "session_id": msg.session_id,
        "instance_id": msg.instance_id,
        "payload": msg.payload,
    }
    return json.dumps(data, cls=SafeJSONEncoder)


def deserialize_message(
    data: str | bytes,
    type_mapping: Optional[dict[str, MessageType]] = None,
) -> Optional[Message]:
    """
    Parse JSON string to Message.

    Args:
        data: JSON string from WebSocket
        type_mapping: Optional custom type mapping (defaults to SERVER_EVENT_TYPES)

    Returns:
        Message object, or None if parsing failed
    """
    try:
        # Ensure data is valid UTF-8 string
        if isinstance(data, bytes):
            data = data.decode("utf-8", errors="replace")
        elif isinstance(data, str):
            data = data.encode("utf-8", errors="replace").decode("utf-8")

        obj = json.loads(data)

        # Server sends event_type, client sends action
        event_type = obj.get("event_type") or obj.get("action")
        if not event_type:
            return None

        # Use provided mapping or default
        mapping = type_mapping or SERVER_EVENT_TYPES

        # Map event type to MessageType
        msg_type = mapping.get(event_type)
        if msg_type is None:
            # Try to find by value in base types
            try:
                msg_type = MessageType(event_type)
            except ValueError:
                return None

        return Message(
            type=msg_type,
            payload=obj.get("payload", {}),
            session_id=obj.get("session_id", ""),
            instance_id=obj.get("instance_id", ""),
            timestamp=time.time(),
        )

    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def create_ping_message(instance_id: str) -> Message:
    """Create a ping message for keep-alive."""
    return Message(
        type=MessageType.PING,
        instance_id=instance_id,
        payload={},
    )
