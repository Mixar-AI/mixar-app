# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""HTTP + WebSocket client for live-rig rooms on the Mixar backend."""

from __future__ import annotations

import uuid
from typing import Any, Optional

from mixar.config.config import get_server_url
from mixar.config.logging_config import get_logger
from mixar.modules.auth.core.auth import get_access_token
from mixar.modules.common.api.client import get_http_client
from mixar.modules.common.websocket import (
    Message,
    MessageType,
    cleanup_websocket_client,
    create_websocket_client,
    get_message_queues,
    get_websocket_client,
    register_message_type,
)

from .retarget import BonePose, bone_pose_from_wire, bone_pose_to_wire

logger = get_logger(__name__)

_API_PREFIX = "api/v1/live-rig"
_WS_PATH = "/api/live-rig/ws"


def _register_protocol() -> None:
    for event in ("live_rig.pose", "live_rig.presence", "live_rig.joined"):
        register_message_type(event, MessageType.CONNECTED)


_register_protocol()


def create_room(label: str = "") -> dict[str, Any]:
    """POST /api/v1/live-rig/rooms — returns room payload."""
    client = get_http_client()
    response = client.post(f"{_API_PREFIX}/rooms", json={"label": label or "Live Rig"})
    return response.data if isinstance(response.data, dict) else {}


def join_room(room_id: str) -> dict[str, Any]:
    """POST /api/v1/live-rig/rooms/{room_id}/join."""
    client = get_http_client()
    response = client.post(f"{_API_PREFIX}/rooms/{room_id}/join", json={})
    return response.data if isinstance(response.data, dict) else {}


def _ws_url(room_id: str) -> str:
    host = get_server_url().rstrip("/")
    ws_host = host.replace("https://", "wss://").replace("http://", "ws://")
    return f"{ws_host}{_WS_PATH}/{room_id}"


def connect_room(room_id: str, instance_id: str = "") -> str:
    """Open (or replace) the live-rig WebSocket for *room_id*. Returns instance id."""
    cleanup_websocket_client()
    instance = instance_id or str(uuid.uuid4())
    url = _ws_url(room_id)
    token = get_access_token() or ""
    if token and "access_token=" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}access_token={token}"
    client = create_websocket_client(url=url, instance_id=instance)
    client.connect()
    logger.info("live_rig: connected room=%s instance=%s", room_id, instance)
    return instance


def disconnect_room() -> None:
    cleanup_websocket_client()


def _client_connected() -> bool:
    client = get_websocket_client()
    if client is None:
        return False
    return bool(client.is_connected)


def publish_pose(pose: BonePose, instance_id: str) -> None:
    """Enqueue a pose frame for the room (background WS send thread)."""
    if not _client_connected():
        return
    queues = get_message_queues()
    queues.send(
        Message(
            type=MessageType.CONNECTED,
            instance_id=instance_id,
            payload={"event": "live_rig.pose", "pose": bone_pose_to_wire(pose)},
        )
    )


def drain_remote_poses(exclude_instance: str = "") -> list[BonePose]:
    """Pull inbound pose messages from the shared WS queue."""
    queues = get_message_queues()
    poses: list[BonePose] = []
    while True:
        message = queues.receive()
        if message is None:
            break
        payload = getattr(message, "payload", None) or {}
        if not isinstance(payload, dict):
            continue
        if payload.get("event") != "live_rig.pose":
            continue
        if exclude_instance and getattr(message, "instance_id", "") == exclude_instance:
            continue
        pose_payload = payload.get("pose")
        if isinstance(pose_payload, dict):
            poses.append(bone_pose_from_wire(pose_payload))
    return poses
