# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Skip repeated empty polls only while the last durable archive is unchanged.

All calls run under store's process and OS locks. A cold cache always goes
through journal recovery; stat identities detect another process's writes,
rotation, replacement, deletion and torn tails before a cached acknowledgement.
"""
from collections import OrderedDict

from ..constants import IDLE_CACHE_SESSIONS

_verified = OrderedDict()


def _identity(path):
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def _signature(directory, tail):
    return tuple(_identity(path) for path in
                 (directory / 'manifest.json', directory / 'events', tail))


def _key(owner, packet, scene):
    return owner, packet.get('epoch'), scene


def lookup(directory, owner, packet, scene):
    """Return (hit, ack); None is a valid successful ack for an empty archive."""
    if packet.get('records') or packet.get('status') != 'available':
        return False, None
    cached = _verified.get(directory)
    if cached is None:
        return False, None
    key, tail, signature, ack = cached
    if key != _key(owner, packet, scene) or signature != _signature(directory, tail):
        return False, None
    _verified.move_to_end(directory)
    return True, dict(ack) if ack is not None else None


def discard(directory):
    _verified.pop(directory, None)


def remember(directory, owner, packet, scene, tail, ack):
    if packet.get('status') != 'available':
        return
    _verified[directory] = (_key(owner, packet, scene), tail,
                            _signature(directory, tail), dict(ack) if ack else None)
    _verified.move_to_end(directory)
    while len(_verified) > IDLE_CACHE_SESSIONS:
        _verified.popitem(last=False)
