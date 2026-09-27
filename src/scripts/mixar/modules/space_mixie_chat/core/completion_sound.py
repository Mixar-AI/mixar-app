# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Play a short sound once when the whole agent run finishes.

The selectable sounds come from the backend (see ``sound_catalog.py``), so new
options ship without a client release. A single bundled clip (``CHIME``) stays
as the offline/pre-auth fallback, and ``OFF`` plays nothing. The choice and a
master ``notifications_muted`` switch are persisted config keys, surfaced as a
picker in Edit > Preferences > System.
"""

import logging
import os
import threading

from mixar.config.config import add_config, get_config

from . import sound_catalog

logger = logging.getLogger(__name__)

_ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
# The raw clips are loud; play them softly so they read as gentle notifications.
_VOLUME = 0.25
_CONFIG_KEY = "completion_sound"
_DEFAULT = "CHIME"
# Master mute for agent notifications. When on, no completion sound plays,
# regardless of the picked sound. Persisted like the picker choice.
_MUTE_KEY = "notifications_muted"

# Always-present built-in options. ``CHIME`` is the offline fallback; every
# other option is supplied by the backend catalog.
OFF = "OFF"
CHIME = "CHIME"
_BUNDLED = {CHIME: "task_complete.mp3"}

_device = None


def available_sounds() -> list:
    """Picker options as ``(value, label)``: OFF, built-in Chime, then catalog."""
    options = [(OFF, "Off"), (CHIME, "Chime")]
    for sound in sound_catalog.get_sounds():
        options.append((sound["id"], sound["label"]))
    return options


def _valid_values() -> set:
    return {value for value, _label in available_sounds()}


def get_completion_sound() -> str:
    """The selected completion sound value (``OFF`` / ``CHIME`` / catalog id)."""
    value = str(get_config().get(_CONFIG_KEY, _DEFAULT))
    return value if value in _valid_values() else _DEFAULT


def set_completion_sound(value: str) -> bool:
    """Persist the completion-sound choice."""
    return add_config(_CONFIG_KEY, str(value))


def get_notifications_muted() -> bool:
    """Whether agent notifications are muted (master switch)."""
    return bool(get_config().get(_MUTE_KEY, False))


def set_notifications_muted(muted: bool) -> bool:
    """Persist the notifications mute choice."""
    return add_config(_MUTE_KEY, bool(muted))


def _play_file(path: str) -> None:
    """Play a local audio file softly (best effort; never raises)."""
    global _device
    if not path or not os.path.isfile(path):
        return
    try:
        import aud

        if _device is None:
            _device = aud.Device()
        handle = _device.play(aud.Sound(path))
        handle.volume = _VOLUME
    except Exception as exc:  # noqa: BLE001 — sound is never critical
        logger.debug("completion sound unavailable: %s", exc)


def play_sound(value: str) -> None:
    """Play one completion sound by value (best effort; never raises).

    ``OFF`` (or an unknown value) plays nothing. Built-in sounds play from the
    bundled asset; catalog sounds play from the on-disk clip cache, downloading
    it first on a background thread if it is not cached yet.
    """
    value = str(value)
    if value == OFF or not value:
        return

    bundled = _BUNDLED.get(value)
    if bundled:
        _play_file(os.path.join(_ASSETS_DIR, bundled))
        return

    cached = sound_catalog.cached_clip_path(value)
    if cached:
        _play_file(cached)
        return

    # Not cached yet: fetch on a worker, then marshal playback to the main
    # thread. A first play may therefore be silent until the clip lands.
    sound = sound_catalog.find_sound(value)
    if not sound:
        return

    def _worker():
        path = sound_catalog.download_clip(sound)
        if not path:
            return
        try:
            import bpy

            bpy.app.timers.register(
                lambda: (_play_file(path), None)[1], first_interval=0.0
            )
        except Exception:  # noqa: BLE001 — headless: play inline
            _play_file(path)

    threading.Thread(
        target=_worker, name="mixar-sound-fetch", daemon=True
    ).start()


def play_completion_sound() -> None:
    """Play the selected task-completion sound (best effort; never raises).

    Does nothing while notifications are muted.
    """
    if get_notifications_muted():
        return
    play_sound(get_completion_sound())
