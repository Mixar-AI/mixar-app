# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""What the user is asked: the startup restore block and Unsaved Work.

- The startup offer (``runtime.current_offer``) heads the splash, or the
  dialog when there is no splash.
- Unsaved Work lists every crashed session that can still be opened
  (``decision.unsaved_sessions``): up to ``MAX_SPLASH`` rows in the splash
  (the session the restore block already offers is left out) with More…, and
  the whole list from File > Recover > Unsaved Work…. A session another
  running Mixar holds is never listed; a row is checked again on click.

The journals are read at startup, when the splash opens again and when the
dialog opens: never on every redraw. Every row restores through
``runtime.restore_entry``, the same flow as the startup offer.
"""

from __future__ import annotations

import os
import time

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import iface_

from . import decision, journal, runtime, telemetry

logger = get_logger(__name__)

MAX_SPLASH = 3
_cache = {"entries": []}


# =============================================================================
# The list
# =============================================================================

def scan() -> list:
    """Read the journals now and keep the result for drawing. Never raises."""
    try:
        jr = runtime._state["journal"]
        skip = set()
        if jr is not None:
            # The session this launch restored from waits for its confirmation.
            attempt = jr.data.get("restore_attempt") or {}
            skip.add(attempt.get("from_session") or "")
            skip |= {os.path.basename(p.get("source_dir") or "")
                     for p in jr.data.get("inherited_points") or []}
        _cache["entries"] = decision.unsaved_sessions(
            journal.list_sessions(runtime.recovery_root()),
            own_session=jr.session if jr is not None else "", skip=skip - {""},
            autosaves=decision.native_autosaves(runtime.tempdir_base()),
        )
    except Exception as e:  # noqa: BLE001 - the splash must draw whatever happens
        logger.debug(f"[RECOVERY] unsaved work scan skipped: {e}")
        _cache["entries"] = []
    return list(_cache["entries"])


def entries() -> list:
    return list(_cache["entries"])


def find(session_id: str) -> dict | None:
    """The entry for ``session_id`` as it is on disk NOW (its lock free)."""
    return next((e for e in scan() if e.get("session") == session_id), None)


def splash_entries() -> list:
    offer = runtime.current_offer()
    shown = offer.get("session") if offer else None
    return [e for e in _cache["entries"] if e.get("session") != shown]


def age_text(at: float, now: float) -> str:
    seconds = max(0.0, now - float(at or 0.0))
    if seconds < 60:
        return iface_("just now")
    if seconds < 3600:
        return iface_("{count} min ago").format(count=int(seconds // 60))
    if seconds < 86400:
        return iface_("{count} h ago").format(count=int(seconds // 3600))
    return iface_("{count} days ago").format(count=int(seconds // 86400))


def entry_text(entry: dict, now: float) -> str:
    """``<document or Untitled> · <age of its best save point> · <tabs>``."""
    target = entry["target"]
    parts = [entry.get("name") or iface_("Untitled"), age_text(target.get("at"), now)]
    tabs = len(target.get("scenes") or [])
    if tabs == 1:
        parts.append(iface_("1 tab"))
    elif tabs > 1:
        parts.append(iface_("{count} tabs").format(count=tabs))
    return " · ".join(parts)


# =============================================================================
# Drawing
# =============================================================================



def draw_offer(layout, *, in_splash: bool) -> bool:
    """The restore block (splash head or dialog body). False when nothing
    is offered."""
    offer = runtime.current_offer()
    if offer is None:
        return False
    if in_splash:
        telemetry.note_offered("splash", offer)
    text = runtime.describe(offer)
    box = layout.box() if in_splash else layout
    if in_splash:
        box.emboss = 'NORMAL'
    col = box.column(align=False)
    col.label(text=text["title"], icon='RECOVER_LAST')
    col.label(text=text["detail"])
    if in_splash:
        row = col.row()
        row.scale_y = 1.4
        row.operator("mixar.restore_crashed_session", text=iface_("Restore"), icon='RECOVER_LAST')
        row.operator("mixar.discard_crashed_session", text=iface_("Start fresh")).surface = 'SPLASH'
        layout.separator()
    else:
        col.operator("mixar.discard_crashed_session", text=iface_("Start fresh"),
                     emboss=False).surface = 'DIALOG'
    return True


def _restore_row(layout, entry: dict, now: float, surface: str) -> None:
    row = layout.row()
    row.operator_context = 'INVOKE_DEFAULT'
    op = row.operator("mixar.restore_unsaved_session", text=entry_text(entry, now),
                      icon='RECOVER_LAST', translate=False)
    op.session = entry.get("session") or ""
    op.surface = surface


def draw_splash_unsaved(layout, items: list) -> None:
    """The splash's full-width Unsaved Work grid (``items``: ``splash_entries``)."""
    from mixar.modules.common.utils.ui_utils import two_column_cells
    layout.label(text="Unsaved Work")
    now = time.time()
    shown = items[:MAX_SPLASH]
    more = len(items) > MAX_SPLASH
    cells = two_column_cells(layout, len(shown) + more)
    for cell, entry in zip(cells, shown):
        _restore_row(cell, entry, now, 'SPLASH')
    if more:
        row = cells[-1].row()
        row.operator_context = 'INVOKE_DEFAULT'
        row.operator("mixar.unsaved_work", text=iface_("More…"), icon='VIEWZOOM')


def draw_unsaved_list(layout) -> None:
    """The full list (File > Recover > Unsaved Work…)."""
    items = entries()
    col = layout.column()
    if not items:
        col.label(text="No unsaved work to recover", icon='INFO')
        return
    col.label(text="Work Mixar saved before it closed unexpectedly", icon='RECOVER_LAST')
    now = time.time()
    for entry in items:
        _restore_row(col, entry, now, 'FILE_MENU')
    col.separator()
    col.label(text="Nothing is written to your project until you save.")
    col.label(text="Each copy is kept for up to 14 days.")
