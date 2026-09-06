# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Onboarding Bootstrap

Owns the trigger that opens the Mixar welcome dialog on launch. The
welcome must appear *after* Blender's splash is gone, otherwise the
user's next click on the splash dismisses the popup as an
outside-click. We solve this with three layered safeguards:

1. ``load_post`` handler that skips the very first invocation.
   Blender fires ``load_post`` once for its own boot-time home file
   load (which happens before / while the splash is showing). The
   second invocation is the user picking a template from the splash
   ("General", "2D Animation", …) — that's the one we want.

2. A long fallback timer that catches the splash-dismissed-with-Esc /
   splash-disabled-in-prefs cases (no template click → no second
   load_post). It only acts if ``_welcome_shown`` is still False.

3. The dialog invoker itself retries every 500 ms until the welcome
   operator is registered, since Mixar's UI auto-discovery loads
   ~415 files in 4 ms-per-frame batches and the operator might not
   be up yet at the moment load_post fires.
"""

import bpy
from bpy.app.handlers import persistent

from mixar.config.logging_config import get_logger
from mixar.modules.onboarding.constants import (
    ONBOARDING_DEV_ALWAYS_ON,
    OP_CARD_MODAL,
    OP_WELCOME,
    WELCOME_FALLBACK_DELAY_SECONDS,
    WELCOME_POST_LOAD_DELAY_SECONDS,
)

logger = get_logger(__name__)

# Session-scoped guard: True once the welcome dialog has been
# successfully invoked. The load_post handler, fallback timer, and
# retry loop all short-circuit on this.
_welcome_shown = False

# Counts ``load_post`` invocations within this Blender session so we
# can skip the first one (Blender's own boot-time home file load).
_load_post_count = 0


def _operator_registered() -> bool:
    """True iff every operator the welcome flow needs is callable.

    Mixar's UI auto-loader runs in 4 ms/frame batches — when the
    handler fires, neither the welcome shim nor the card modal it
    transitions into may be registered yet. We wait for both before
    firing so the chain doesn't break mid-step.
    """
    for op_path in (OP_WELCOME, OP_CARD_MODAL):
        namespace, op_name = op_path.split(".", 1)
        op_namespace = getattr(bpy.ops, namespace, None)
        if op_namespace is None or not hasattr(op_namespace, op_name):
            return False
    return True


def _invoke_welcome_dialog():
    """Timer callback. Invokes the welcome dialog when the operator is
    registered, otherwise asks the timer to retry shortly. Idempotent
    via ``_welcome_shown``.
    """
    global _welcome_shown
    if _welcome_shown:
        return None

    if not _operator_registered():
        return 0.2

    namespace, op_name = OP_WELCOME.split(".", 1)
    op = getattr(getattr(bpy.ops, namespace), op_name)

    try:
        op("INVOKE_DEFAULT")
        _welcome_shown = True
    except Exception as exc:
        logger.warning("Onboarding welcome failed to launch: %s", exc)
        return 0.5
    return None


def _schedule_welcome(delay: float) -> None:
    if _welcome_shown:
        return
    if bpy.app.timers.is_registered(_invoke_welcome_dialog):
        return
    bpy.app.timers.register(_invoke_welcome_dialog, first_interval=delay)


def _end_onboarding() -> None:
    """Force the onboarding into the DONE state. Used when the user
    opens a fresh file mid-session — the dim film should disappear
    so they can work in a clean editor.
    """
    try:
        from mixar.modules.onboarding.constants import STEP_DONE
        from mixar.modules.onboarding.core import state
        state.transition_to(STEP_DONE)
    except Exception as exc:
        logger.debug("Onboarding: end-onboarding failed: %s", exc)


def _drop_card_texture_cache() -> None:
    try:
        from mixar.modules.onboarding.core.card import image_loader
        image_loader.reset_cache()
    except Exception as exc:
        logger.debug("Onboarding: card texture cache reset skipped: %s", exc)


@persistent
def _on_load_post(_dummy):
    """``load_post`` runs on every file open. We split it into three
    cases:

    * Count 1 — Blender's own boot load that happens before the
      splash is even drawn. Skipped.
    * Count 2 — the user picking a template from the splash. Schedule
      the welcome if it hasn't already shown. The default Cube /
      Light / Camera that ship with Blender's factory startup are
      left in place so the user has something visible in the
      viewport during the tour.
    * Count 3+ — the user opened a fresh file *after* Mixar was up.
      End any in-flight onboarding so the dim film disappears for
      the new file.

    Marked ``@persistent`` so the handler survives the very
    ``read_homefile`` call that fired it.
    """
    global _load_post_count
    _load_post_count += 1
    # The card renderer caches GPUTextures borrowed from Image datablocks
    # (gpu.texture.from_image — owned by the image, not by Python). A file
    # load frees every image, so a cached handle sampled by the next tour
    # draw is a freed GL texture. Drop the cache on every load, first
    # (boot-time) load included.
    _drop_card_texture_cache()
    if _load_post_count < 2:
        return
    if _load_post_count == 2:
        if _welcome_shown:
            return
        _schedule_welcome(WELCOME_POST_LOAD_DELAY_SECONDS)
        return
    # Count 3 onwards: a mid-session file load. End the tour.
    _end_onboarding()


def _fallback_timer():
    """Catches the splash dismissal paths that fire no load_post:
    user hits Esc / clicks outside the splash, or has the splash
    disabled in preferences. Long delay — by the time it fires we're
    confident the splash is gone and the UI loader has finished.
    """
    if _welcome_shown:
        return None
    return _invoke_welcome_dialog()


def _should_show_welcome() -> bool:
    if ONBOARDING_DEV_ALWAYS_ON:
        return True
    # Real first-run gate will live here once we wire up addon prefs.
    return False


def _install_overlay_handlers_once():
    """Register the dim film + step highlight GPU draw handlers.

    Logged at INFO so we can verify the overlay is actually wired up
    when debugging — silent debug-level logs masked an earlier set of
    failures.
    """
    try:
        from mixar.modules.onboarding.core.overlay import (
            highlight,
            overlay_renderer,
        )
    except Exception as exc:
        logger.warning(
            "Onboarding overlay import failed (will retry): %s", exc,
        )
        return 1.0
    try:
        overlay_renderer.install_draw_handlers()
        logger.info(
            "Onboarding overlay: dim handlers installed (%d)",
            len(overlay_renderer._handles),
        )
    except Exception as exc:
        logger.warning("Onboarding dim install failed: %s", exc)
    try:
        highlight.install_draw_handlers()
    except Exception as exc:
        logger.warning("Onboarding highlight install failed: %s", exc)
    return None


def register():
    global _welcome_shown, _load_post_count
    _welcome_shown = False
    _load_post_count = 0

    # Install overlay draw handlers unconditionally so the dim film
    # and step-highlight border are ready for when the auth-triggered
    # welcome eventually fires. Without this, the very first user to
    # sign in would see a card with no dim/highlight underneath.
    retry = _install_overlay_handlers_once()
    if retry is not None and not bpy.app.timers.is_registered(
        _install_overlay_handlers_once
    ):
        bpy.app.timers.register(
            _install_overlay_handlers_once, first_interval=retry,
        )

    # The boot-time fallback path (load_post handler + long timer)
    # only runs in the dev override mode. In production the welcome
    # is triggered from the auth-success hook the first time a user
    # signs in — see ``auth_hooks.maybe_show_onboarding``.
    if not _should_show_welcome():
        logger.debug(
            "Onboarding boot-time auto-fire disabled — "
            "welcome will be triggered by the auth hook on first sign-in"
        )
        return

    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)

    if not bpy.app.timers.is_registered(_fallback_timer):
        bpy.app.timers.register(
            _fallback_timer,
            first_interval=WELCOME_FALLBACK_DELAY_SECONDS,
        )

    logger.debug(
        "Onboarding dev auto-fire armed (load_post + %ss fallback)",
        WELCOME_FALLBACK_DELAY_SECONDS,
    )


def unregister():
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    _drop_card_texture_cache()
    for fn in (
        _fallback_timer,
        _invoke_welcome_dialog,
        _install_overlay_handlers_once,
    ):
        if bpy.app.timers.is_registered(fn):
            bpy.app.timers.unregister(fn)
    try:
        from mixar.modules.onboarding.core.overlay import (
            highlight,
            overlay_renderer,
        )
        overlay_renderer.remove_draw_handlers()
        highlight.remove_draw_handlers()
    except Exception as exc:
        logger.debug("Onboarding overlay teardown skipped: %s", exc)
