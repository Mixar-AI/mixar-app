# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Global Project Rules — disk store.

Global rules apply to EVERY .mixar file the user opens (per-file rules
live in ``scene.mixie_chat_rules``). They are a sidecar JSON, same
convention and folder as the chat history store:

    ~/.mixar/global_rules.json

The payload is the same compact list format as the scene store
(``core/rules.py:parse_rules`` / ``serialize_rules``):
``[{"text": str, "enabled": bool}, ...]`` — so both stores share one
parser and one size cap. All reads/writes are best-effort: a broken or
unreadable file behaves as "no global rules" and is rewritten on the
next edit.
"""

import os

from mixar.config.logging_config import get_logger

from ..constants import CHAT_RULES_MAXLEN
from .rules import parse_rules, serialize_rules

logger = get_logger(__name__)

_FILENAME = "global_rules.json"


def _store_path() -> str:
    base = os.path.join(os.path.expanduser("~"), ".mixar")
    return os.path.join(base, _FILENAME)


def load_global_rules() -> list:
    """Read the global rule list; missing/broken file = no rules."""
    path = _store_path()
    try:
        if not os.path.isfile(path):
            return []
        with open(path, "r", encoding="utf-8") as fh:
            raw = fh.read()
        return parse_rules(raw)
    except Exception:
        logger.warning("global rules store unreadable: %s", path, exc_info=True)
        return []


def save_global_rules(rules: list) -> bool:
    """Persist the global rule list. False when it exceeds the cap.

    Atomic-ish write (temp file + replace) so a crash mid-write never
    leaves a truncated store behind.
    """
    raw = serialize_rules(rules)
    if len(raw.encode('utf-8')) > CHAT_RULES_MAXLEN - 1:
        return False
    path = _store_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(raw if raw else "[]")
        os.replace(tmp, path)
        return True
    except OSError:
        logger.error("failed to write global rules store: %s", path, exc_info=True)
        return False
