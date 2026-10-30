# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Engine calls made off the main thread, before their script runs.

The backend's ``engine_*`` tools reach the engine through a two-line script
(``modules/agent/tools/domains/engine.py:_link``)::

    from mixar.modules.space_mixie_chat.core.engine_link import link_call
    result = {'engine_link': link_call(**json.loads('{"tool": "playtest", ...}'))}

Run as it stands, that script would hold Blender's main thread for the whole
engine call — a playtest is minutes — freezing Mixar's UI and every other
scene tab's scripts (Sky Temple QA run, 2026-10-30). As with texture
prefetch (``script_prefetch``), the call starts on a worker thread the moment
the script arrives on the WebSocket thread; the script's lane holds it
(``PENDING``, one flag check a tick) until the answer is stored in
``engine_link``, and the script then takes it at once.

Engine calls run one at a time (there is one editor, and it answers one call
at a time anyway). A call past its own timeout (+ headroom) stores a timeout
answer, so the script is never left to call the engine itself.
"""

from __future__ import annotations

import ast
import json
import re
import threading
import time
from typing import Optional

from mixar.config.logging_config import get_logger

from . import engine_link
from .script_prefetch import PENDING, READY

logger = get_logger(__name__)

_SCRIPT = re.compile(
    r"^from mixar\.modules\.space_mixie_chat\.core\.engine_link import (\w+)\n"
    r"result = \{'engine_link': (\w+)\(\*\*json\.loads\((.+)\)\)\}\n", re.MULTILINE)
PREFETCHABLE = {"link_status", "link_call", "link_import", "link_build_manifest", "link_upload_build"}
# Each call's own budget when it names none (engine_link's defaults), plus headroom.
DEFAULT_TIMEOUT_S = {"link_status": 10.0, "link_build_manifest": 10.0,
                     "link_upload_build": engine_link.UPLOAD_TIMEOUT_S, "link_import": 180.0}
HEADROOM_S = 30.0
_engine_lock = threading.Lock()


def parse(script: str) -> Optional[tuple[str, dict]]:
    """(function, kwargs) of an engine-call script, or None."""
    match = _SCRIPT.search(script or "")
    if not match or match.group(1) != match.group(2) or match.group(1) not in PREFETCHABLE:
        return None
    try:
        kwargs = json.loads(ast.literal_eval(match.group(3)))
    except (ValueError, SyntaxError, TypeError):
        return None
    return (match.group(1), kwargs) if isinstance(kwargs, dict) else None


class EngineCallPrefetch:
    """One engine call on a worker thread; READY once its answer is stored."""

    url_count = 0

    def __init__(self, fn: str, kwargs: dict):
        self.fn, self.kwargs = fn, kwargs
        self.key = engine_link.call_key(fn, kwargs)
        budget = kwargs.get("timeout") or DEFAULT_TIMEOUT_S.get(fn, 60.0)
        self._deadline = time.monotonic() + float(budget) + HEADROOM_S
        self._done = threading.Event()
        self._settled = threading.Lock()  # the answer is stored once: the call's, or the timeout's
        self._stored = False
        threading.Thread(target=self._run, name="mixar-engine-call", daemon=True).start()

    def _store(self, result: dict) -> None:
        with self._settled:
            if self._stored:
                return
            self._stored = True
        engine_link.store_prefetched(self.key, result)
        self._done.set()

    def _run(self) -> None:
        started = time.monotonic()
        try:
            with _engine_lock:
                result = getattr(engine_link, self.fn).__wrapped__(**self.kwargs)
        except Exception as exc:  # noqa: BLE001 - the answer says what failed
            logger.warning("engine call %s failed: %s", self.fn, type(exc).__name__)
            result = {"success": False, "error": f"The engine call failed ({type(exc).__name__})."}
        logger.debug("engine call %s answered in %.1fs", self.fn, time.monotonic() - started)
        self._store(result)

    def state(self) -> str:
        if self._done.is_set():
            return READY
        if time.monotonic() >= self._deadline:
            self._store({"success": False,
                         "error": "The engine did not answer in time; its work may still be running. "
                                  "Check engine_status before repeating the call."})
            return READY
        return PENDING

    def ready(self) -> bool:
        return self.state() == READY

    def failed_urls(self) -> list:
        return []


def maybe_start(script: str) -> Optional[EngineCallPrefetch]:
    call = parse(script)
    if call is None:
        return None
    fn, kwargs = call
    if fn == "link_import" and str(kwargs.get("destination") or "").lower() == "project":
        return None  # resolving the .blend's own folder reads bpy: keep it on the main thread
    return EngineCallPrefetch(fn, kwargs)
