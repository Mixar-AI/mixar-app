# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Selection-assist engine: the suggestion state machine.

A 0.25s timer polls the selection (names only — cheap) and, on a genuine
user selection change, rebuilds the suggestion ladder. Cycling through
levels is applied only from the expand/shrink operators (real operator
context, undo-pushed); the timer only ever *detects* and *previews*.

Ghost preview: the names the next accept would add are written to
``scene.mixar_suggested_outline`` (see constants.GHOST_PROP), which the
C++ overlay engine picks up to draw suggested-category outlines. The
engine tracks the selection state it just created (``_expected``) so its
own applies never re-trigger ladder rebuilds.

Suppressed while an AGENT turn is executing — the viewport lock owns the
viewport then, and agent-driven selection churn must not spawn chips.
"""

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.agent_viewport_lock.core.state_probe import is_agent_executing

from ..constants import (
    ENABLE_PROP,
    GHOST_PROP,
    GHOST_SEP,
    MAX_GHOST_OBJECTS,
    MAX_LEVEL_OBJECTS,
    POLL_INTERVAL,
)
from .ladder import build_ladder
from .registry import REGISTRY

logger = get_logger(__name__)


def _tag_view3d_redraw():
    try:
        wm = bpy.context.window_manager
        for window in wm.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
    except Exception:
        pass


class SelectionAssistEngine:
    """Singleton (see ENGINE below). Main-thread only: timer + operators."""

    def __init__(self):
        self.reset()

    def reset(self):
        self._ladder = []
        self._idx = -1          # -1: nothing applied yet, seed selection live
        self._seed = frozenset()
        self._last = None       # last observed (selection, active) state
        self._expected = None   # state we just created via _apply
        self._ghost_value = None  # last string written to GHOST_PROP
        self._ghost_pending = False  # debounce: publish ghost one tick later

    # -- polling -------------------------------------------------------------

    def on_timer(self):
        try:
            self._poll()
        except Exception:
            logger.debug("selection assist poll failed", exc_info=True)
        return POLL_INTERVAL

    def _poll(self):
        context = bpy.context
        scene = context.scene
        view_layer = context.view_layer
        if scene is None or view_layer is None:
            return

        wm = context.window_manager
        enabled = bool(getattr(wm, ENABLE_PROP, True)) if wm else True
        # Timer contexts can lack `mode` early in startup — treat as not-object.
        mode_ok = getattr(context, "mode", "") == 'OBJECT'
        if not enabled or not mode_ok or is_agent_executing(scene):
            self._deactivate(scene)
            return

        active = view_layer.objects.active
        state = (
            frozenset(o.name for o in view_layer.objects.selected),
            active.name if active else None,
        )
        if state == self._last:
            # Debounced ghost: the selection survived one full poll tick
            # unchanged — now it is worth previewing. Publishing on the very
            # click made rapid click-around light up green everywhere, which
            # read as the app selecting objects on its own.
            if self._ghost_pending:
                self._ghost_pending = False
                self._write_ghost(scene, self._next_preview())
                _tag_view3d_redraw()
            return
        self._last = state

        if state == self._expected:
            # Our own apply — keep the ladder, just refresh the preview.
            self._write_ghost(scene, self._next_preview())
            return

        # Genuine user selection change: rebuild the ladder from this seed.
        selected, active_name = state
        self._ladder = []
        self._idx = -1
        self._seed = selected | ({active_name} if active_name else set())
        self._expected = None
        if active_name and selected:
            index = REGISTRY.index(view_layer)
            self._ladder = build_ladder(
                index, active_name, selected, max_level_objects=MAX_LEVEL_OBJECTS
            )
        # Clear any stale ghost now; the new preview lands next tick (the
        # chip shows immediately — it is small and non-alarming).
        self._ghost_pending = bool(self._ladder)
        self._write_ghost(scene, frozenset())
        _tag_view3d_redraw()

    def _deactivate(self, scene):
        if self._ladder or self._ghost_value:
            self._ladder = []
            self._idx = -1
            self._expected = None
            self._last = None
            self._ghost_pending = False
            self._write_ghost(scene, frozenset())
            _tag_view3d_redraw()

    # -- cycling (called from operators, real context) ------------------------

    def can_expand(self):
        return self._idx + 1 < len(self._ladder)

    def can_shrink(self):
        # idx >= 0: can step back. idx == -1 with a ladder: can dismiss.
        return self._idx >= 0 or bool(self._ladder)

    def expand(self, context):
        if not self.can_expand():
            return False
        self._idx += 1
        self._apply(context, self._ladder[self._idx].names)
        return True

    def shrink(self, context):
        if self._idx == -1:
            if not self._ladder:
                return False
            # Dismiss: the user wants exactly what they selected — drop the
            # suggestion (ghost + chip) until the selection changes again.
            self._ladder = []
            self._ghost_pending = False
            self._write_ghost(context.scene, frozenset())
            _tag_view3d_redraw()
            return True
        self._idx -= 1
        names = self._ladder[self._idx].names if self._idx >= 0 else self._seed
        self._apply(context, names)
        return True

    def _apply(self, context, names):
        view_layer = context.view_layer
        active = view_layer.objects.active
        for obj in view_layer.objects:
            try:
                obj.select_set(obj.name in names, view_layer=view_layer)
            except RuntimeError:
                pass  # unselectable/hidden edge cases — skip, never abort the batch
        # Active object stays — it is the user's semantic anchor and the
        # ladder was computed from it.
        applied = (
            frozenset(o.name for o in view_layer.objects.selected),
            active.name if active else None,
        )
        self._expected = applied
        self._last = applied
        # Explicit accept — preview the next hop immediately, no debounce.
        self._ghost_pending = False
        self._write_ghost(context.scene, self._next_preview())
        _tag_view3d_redraw()

    # -- ghost + chip ----------------------------------------------------------

    def _current_names(self):
        if self._idx >= 0:
            return self._ladder[self._idx].names
        return self._seed

    def _next_preview(self):
        """Names the next expand would ADD — the ghost outline set."""
        nxt = self._idx + 1
        if nxt >= len(self._ladder):
            return frozenset()
        preview = self._ladder[nxt].names - self._current_names()
        if len(preview) > MAX_GHOST_OBJECTS:
            return frozenset()
        return preview

    def _write_ghost(self, scene, names):
        value = GHOST_SEP.join(sorted(names)) if names else ""
        if value == self._ghost_value:
            return
        try:
            setattr(scene, GHOST_PROP, value)
            self._ghost_value = value
        except Exception:
            logger.debug("selection assist: ghost prop write failed", exc_info=True)

    def chip_segments(self):
        """Chip content as (is_key, text) segments, or None to hide."""
        if not self._ladder:
            return None
        if self._idx < 0:
            # Nothing accepted yet — pure suggestion.
            nxt = self._ladder[0]
            return [
                (False, "Suggestion: " + nxt.label),
                (True, "="),
                (False, "select"),
                (True, "-"),
                (False, "dismiss"),
            ]
        segments = [
            (False, "{} ({}/{})".format(
                self._ladder[self._idx].label, self._idx + 1, len(self._ladder))),
        ]
        if self._idx + 1 < len(self._ladder):
            segments += [(True, "="), (False, "next")]
        segments += [(True, "-"), (False, "back")]
        return segments


ENGINE = SelectionAssistEngine()
