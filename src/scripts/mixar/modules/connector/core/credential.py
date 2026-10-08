# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Per-launch loopback credential for the connector sidecar.

The sidecar is reachable by every process on the machine (and by every web
page the browser lets talk to ``127.0.0.1``), so nothing is served without
the bearer token minted here. The token never leaves the machine: it is handed
to the hub through a private discovery record, the same way the MCP relay
hands its credential to the bundled launcher (``mcp_bridge/core/discovery``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import uuid

RECORD_VERSION = 1


def new_token() -> str:
    return secrets.token_urlsafe(32)


def discovery_directory() -> Path:
    override = os.environ.get("MIXAR_CONNECTOR_DISCOVERY_DIR")
    return Path(override).expanduser() if override else Path.home() / ".mixar" / "connector"


def publish(port: int, token: str) -> Path:
    """Write ``<pid>.json`` for the hub; private to this user, never a symlink."""
    directory = discovery_directory()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink():
        raise OSError("Connector discovery directory must not be a symlink")
    if os.name != "nt":
        if directory.stat().st_uid != os.getuid():
            raise OSError("Connector discovery directory belongs to another user")
        directory.chmod(0o700)
    path = directory / (str(os.getpid()) + ".json")
    temporary = directory / ("." + uuid.uuid4().hex)
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"version": RECORD_VERSION, "pid": os.getpid(), "port": port,
                       "token": token}, stream)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def unpublish(path: Path | None) -> None:
    if path is not None:
        path.unlink(missing_ok=True)
