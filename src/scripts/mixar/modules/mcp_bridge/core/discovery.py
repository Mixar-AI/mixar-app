# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Local connector discovery. Only a loopback credential ever reaches disk."""

import json
import os
from pathlib import Path
import re
import stat
import uuid

_CHUNK_SIZE = re.compile(rb"([0-9A-Fa-f]+)(?:;[^\r\n]*)?\r\n")


def read_body(response, limit):
    """Up to limit+1 bytes of a relay response body (http.client response).

    The relay answers HTTP/1.0 with Content-Length and closes the connection.
    Some Windows security software rewrites that to "transfer-encoding: chunked"
    without chunking the body, and http.client then fails with IncompleteRead
    (Discord report, Oct 2026). A "chunked" reply is therefore read up to the
    close and de-chunked only if it really is chunked; relay bodies are JSON
    objects, which never start with a hex chunk size.
    """
    if not response.chunked:
        return response.read(limit + 1)
    raw = response.fp.read(limit + 1)
    if not _CHUNK_SIZE.match(raw):
        return raw
    body, at = [], 0
    while match := _CHUNK_SIZE.match(raw, at):
        size, at = int(match.group(1), 16), match.end()
        if size == 0:
            return b"".join(body)
        if raw[at + size:at + size + 2] != b"\r\n":
            break
        body.append(raw[at:at + size])
        at += size + 2
    raise ValueError("Malformed chunked MCP response")


def discovery_directory():
    override = os.environ.get("MIXAR_MCP_DISCOVERY_DIR")
    return Path(override).expanduser() if override else Path.home() / ".mixar" / "mcp"


def publish(port, token, instance_id):
    directory = discovery_directory()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink():
        raise OSError("MCP discovery directory must not be a symlink")
    if os.name != "nt":
        if directory.stat().st_uid != os.getuid():
            raise OSError("MCP discovery directory belongs to another user")
        directory.chmod(0o700)
    path = directory / (str(os.getpid()) + ".json")
    temporary = directory / ("." + uuid.uuid4().hex)
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"version": 1, "pid": os.getpid(), "port": port,
                       "token": token, "instance_id": instance_id}, stream)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def read_record(path):
    """Reject redirects, other users' records, and arbitrary network addresses."""
    path = Path(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 4096:
            raise ValueError("Invalid MCP discovery record")
        if os.name != "nt" and (info.st_uid != os.getuid() or info.st_mode & 0o077):
            raise ValueError("MCP discovery record must be private to this user")
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            fd = None
            record = json.load(stream)
    finally:
        if fd is not None:
            os.close(fd)
    if (not isinstance(record, dict) or record.get("version") != 1
            or type(record.get("port")) is not int or not 1 <= record["port"] <= 65535
            or not isinstance(record.get("token"), str) or len(record["token"]) < 32):
        raise ValueError("Invalid MCP discovery record")
    return record
