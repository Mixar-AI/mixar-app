# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — WindowManager properties.

Two JSON strings the running tour publishes for the QA harness:

* ``mixar_tour_state`` — the runner's ``state()`` dict (status, beat, ms,
  gate, …) so a scenario can wait on "beat == 'library'" without screenshots.
* ``mixar_tour_qa_targets`` — the video card's control rects (pause, skip,
  exit, the gate anchor) so ``qa_client`` can click them by name.

Plus the tour language dropdown the first-time splash shows
(``mixar_tour_language``): an EnumProperty whose getter/setter go straight
to ``core/tour/language`` so the value is the persisted per-user choice,
never a copy that could drift from it. Setting it persists the choice and
notifies the language listeners (the pack fetch starts from there).

WindowManager, ``SKIP_SAVE``: per-session UI state, never serialized into
a ``.blend``. The hand-written ``register()`` is required for WM props
(``classes`` stays empty so the auto-discovery fallback has nothing to do).
"""

import json

import bpy
from bpy.app.handlers import persistent

from mixar.config.logging_config import get_logger
from mixar.modules.onboarding.core.tour import language
from mixar.modules.onboarding.core.tour.config import (
    WM_PROP_TOUR_LANGUAGE,
    WM_PROP_TOUR_QA_TARGETS,
    WM_PROP_TOUR_STATE,
)

_logger = get_logger(__name__)

classes = ()


@persistent
def _on_load_pre(*_args):
    """A file load frees every Image, the movie texture included: end a
    running tour first so nothing draws from a freed datablock."""
    try:
        from mixar.modules.onboarding.core.tour import session as tour_session
        live = tour_session.current()
        if live is not None and live.running:
            live.stop("file-loaded")
    except Exception as exc:  # noqa: BLE001
        _logger.debug("tour: load_pre stop failed: %s", exc)


def _language_get(_self) -> int:
    try:
        return language.CODES.index(language.stored())
    except ValueError:
        return 0


def _language_set(_self, index: int) -> None:
    try:
        code = language.CODES[int(index)]
    except (IndexError, ValueError, TypeError):
        code = language.DEFAULT_CODE
    language.set_stored(code)


def _prefetch(code: str) -> None:
    """Start the language pack download; runs on the main thread (the
    property setter / a startup timer) and returns at once."""
    try:
        from mixar.modules.onboarding.core.tour import pack_fetch
        pack_fetch.prefetch(code)
    except Exception as exc:  # noqa: BLE001
        _logger.debug("tour pack prefetch skipped: %s", exc)


def _prefetch_stored_later():
    """Startup: fetch (or resume) the stored language's pack a few seconds
    in, so a download interrupted last session completes without the user
    touching the dropdown again."""
    _prefetch(language.stored())
    return None


def register():
    if _on_load_pre not in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.append(_on_load_pre)
    language.add_listener(_prefetch)
    try:
        bpy.app.timers.register(_prefetch_stored_later, first_interval=5.0)
    except Exception as exc:  # noqa: BLE001
        _logger.debug("tour pack startup prefetch not scheduled: %s", exc)
    setattr(
        bpy.types.WindowManager,
        WM_PROP_TOUR_STATE,
        bpy.props.StringProperty(
            name="Mixar Tour State",
            description="JSON snapshot of the interactive tour's runner state",
            default="",
            options={"SKIP_SAVE"},
        ),
    )
    setattr(
        bpy.types.WindowManager,
        WM_PROP_TOUR_QA_TARGETS,
        bpy.props.StringProperty(
            name="Mixar Tour QA Targets",
            description="JSON list of the tour's clickable control rects",
            default="",
            options={"SKIP_SAVE"},
        ),
    )
    setattr(
        bpy.types.WindowManager,
        WM_PROP_TOUR_LANGUAGE,
        bpy.props.EnumProperty(
            name="Language",
            description="Language the guided tour is narrated in",
            items=language.enum_items(),
            get=_language_get,
            set=_language_set,
            options={"SKIP_SAVE"},
        ),
    )


def unregister():
    language.remove_listener(_prefetch)
    try:
        from mixar.modules.onboarding.core.tour import pack_fetch
        pack_fetch.shutdown()
    except Exception:  # noqa: BLE001
        pass
    try:
        from mixar.modules.onboarding.core.tour import session as tour_session
        live = tour_session.current()
        if live is not None and live.running:
            live.stop("cancelled")
    except Exception:  # noqa: BLE001
        pass
    if _on_load_pre in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(_on_load_pre)
    for attr in (WM_PROP_TOUR_STATE, WM_PROP_TOUR_QA_TARGETS, WM_PROP_TOUR_LANGUAGE):
        if hasattr(bpy.types.WindowManager, attr):
            delattr(bpy.types.WindowManager, attr)


def _publish(wm, attr: str, payload) -> bool:
    if wm is None:
        return False
    try:
        setattr(wm, attr, json.dumps(payload, default=str))
        return True
    except Exception as exc:  # noqa: BLE001 — publishing is best-effort
        _logger.debug("tour props: could not publish %s: %s", attr, exc)
        return False


def publish_state(wm, state: dict) -> bool:
    return _publish(wm, WM_PROP_TOUR_STATE, dict(state or {}))


def publish_qa_targets(wm, targets: list) -> bool:
    return _publish(wm, WM_PROP_TOUR_QA_TARGETS, list(targets or []))
