# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""``[SCENES]`` client ledger for the parallel-scene-tabs work.

One INFO line per scene event in the app log, grep-able by tag and session id,
plus a per-session JSONL dossier under ``~/.mixar/scenes-dossier/<session_id>/``
(override the root with ``MIXAR_SCENES_DOSSIER_DIR``; set it to ``0`` to disable)
so a failing tab can be read from the filesystem. Lives in ``common`` so both the chat add-on and
``common/agent_execution`` can log. The backend writes the same record shape
(``modules/agent/diagnostics/scenes.py``) and
``scripts/scenes_dossier.sh`` merges both by time.

Events: ``route.pin`` / ``route.restore`` / ``route.reject``, ``tab.new``,
``tab.switch``, ``tab.close.<step>``, ``cards.clear`` / ``cards.settle``,
``sweep.lane``, ``commit.target``, ``gen.deliver``, ``undo.banner``,
``poll.start`` / ``poll.stop``.

Never raises.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

TAG = "[SCENES]"
_DOSSIER_FILE = "events.jsonl"
_UNROUTED = "_unrouted"
_SAFE_ID = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_:.")


def session_of(scene: Any) -> str:
    """The chat session id tagged on a scene, or ``""``."""
    if scene is None:
        return ""
    try:
        sid = getattr(scene, "mixie_session_id", "") or ""
        if not sid:
            getter = getattr(scene, "get", None)
            sid = getter("mixie_session_id", "") if callable(getter) else ""
        return str(sid or "")
    except Exception:  # noqa: BLE001
        return ""


def dossier_root() -> str:
    override = os.environ.get("MIXAR_SCENES_DOSSIER_DIR")
    if override is not None:
        return "" if override.strip() in ("", "0", "off") else override
    return os.path.join(os.path.expanduser("~"), ".mixar", "scenes-dossier")


def _fmt(value: Any) -> str:
    text = str(value)
    if " " in text or "=" in text or not text:
        return json.dumps(text)
    return text


def slog(event: str, scene: Any = None, session_id: str | None = None, **fields: Any) -> None:
    """Log one ``[SCENES]`` line and append it to the session's dossier."""
    sid = session_id or session_of(scene)
    scene_name = getattr(scene, "name", None) if scene is not None else None
    parts = [f"{TAG} event={event}", f"session={sid or '-'}"]
    if scene_name:
        parts.append(f"scene={_fmt(scene_name)}")
    parts.extend(f"{key}={_fmt(value)}" for key, value in fields.items())
    try:
        logger.info(" ".join(parts))
    except Exception:  # noqa: BLE001
        pass
    _append_dossier(event, sid, scene_name, fields)


def _append_dossier(event: str, sid: str, scene_name: Any, fields: dict[str, Any]) -> None:
    root = dossier_root()
    if not root:
        return
    folder_name = sid if sid and not (set(sid) - _SAFE_ID) else _UNROUTED
    try:
        folder = os.path.join(root, folder_name)
        os.makedirs(folder, exist_ok=True)
        record = {"ts": time.time(), "side": "client", "event": event,
                  "session_id": sid, "scene": scene_name, **fields}
        with open(os.path.join(folder, _DOSSIER_FILE), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
    except Exception as exc:  # noqa: BLE001
        try:
            logger.debug("%s dossier write skipped: %s", TAG, exc)
        except Exception:  # noqa: BLE001
            pass
