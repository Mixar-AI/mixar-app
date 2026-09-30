# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Registers the active locale's catalog with ``bpy.app.translations``.

Only the catalog serving the current UI locale is parsed and registered (one
file, a few milliseconds); the other languages never cost memory. Changing
Preferences > Interface > Language re-registers through a msgbus subscription
on ``PreferencesView.language`` (re-armed after every file load, which drops
msgbus subscriptions) and redraws every area so already-drawn text updates.
"""

from __future__ import annotations

from mixar.config.logging_config import get_logger

from ..constants import LOCALE_DIR, SOURCE_LOCALE, TRANSLATIONS_OWNER
from . import api
from .catalog import load_locale

logger = get_logger(__name__)

_MSGBUS_OWNER = object()
_state = {"code": None, "locale": None, "registered": False}


def active_catalog() -> str | None:
    """Code of the registered catalog (``None`` for English / no catalog)."""
    return _state["code"]


def _current_locale() -> str:
    from bpy.app import translations
    try:
        return translations.locale or ""
    except Exception:
        return ""


def _unregister_dict() -> None:
    if not _state["registered"]:
        return
    from bpy.app import translations
    try:
        translations.unregister(TRANSLATIONS_OWNER)
    except Exception:
        pass
    _state["registered"] = False


def reload(force: bool = False) -> str | None:
    """(Re)register the catalog for the current locale; returns its code."""
    from bpy.app import translations

    locale = _current_locale()
    if not force and _state["registered"] and locale == _state["locale"]:
        return _state["code"]
    try:
        code, messages = load_locale(locale, LOCALE_DIR)
    except Exception:
        logger.error("Mixar translations: failed to load catalog for %s", locale, exc_info=True)
        code, messages = None, {}
    _unregister_dict()
    _state["locale"] = locale
    _state["code"] = code
    if messages:
        # Keyed by the exact locale Blender reports so its lookup (full
        # locale first) hits this dict whatever alias resolved the catalog.
        translations.register(TRANSLATIONS_OWNER, {locale: messages, code: messages})
        _state["registered"] = True
        logger.info("Mixar translations: %s (%d messages) for locale %s",
                    code, len(messages), locale)
    return code


def _interface_locale() -> str:
    """The locale the interface is actually shown in."""
    try:
        import bpy
        if not bpy.context.preferences.view.use_translate_interface:
            return SOURCE_LOCALE
    except Exception:
        pass
    return _current_locale() or SOURCE_LOCALE


def _sync_ui_locale() -> None:
    """Publish the interface locale to request code; refetch server text
    (the generation catalog is localized by the backend) when it changes."""
    locale = _interface_locale()
    if locale == api.ui_locale():
        return
    api.set_ui_locale(locale)
    for module_name, function in (
        ("mixar.bootstrap.generation_catalog_cache", "refresh_generation_catalog_cache"),
        ("mixar.bootstrap.chat_generate_options_cache", "refresh_chat_generate_options_cache"),
    ):
        try:
            import sys
            module = sys.modules.get(module_name)
            if module is not None:
                getattr(module, function)()
        except Exception:
            logger.debug("Mixar translations: %s refresh failed", module_name, exc_info=True)


def _redraw_all() -> None:
    try:
        import bpy
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
    except Exception:
        pass


def _on_language_changed(*_args) -> None:
    reload()
    _sync_ui_locale()
    _redraw_all()


# Safety net for a language switch msgbus misses (e.g. set from a script
# before the first subscription): a locale comparison every couple of seconds.
_POLL_INTERVAL_S = 2.0


def _poll_locale():
    try:
        if _current_locale() != _state["locale"] or _interface_locale() != api.ui_locale():
            reload()
            _sync_ui_locale()
            _redraw_all()
    except Exception:
        pass
    return _POLL_INTERVAL_S


def _subscribe() -> None:
    import bpy
    try:
        bpy.msgbus.clear_by_owner(_MSGBUS_OWNER)
        for prop in ("language", "use_translate_interface", "use_translate_tooltips",
                     "use_translate_reports"):
            bpy.msgbus.subscribe_rna(
                key=(bpy.types.PreferencesView, prop),
                owner=_MSGBUS_OWNER,
                args=(),
                notify=_on_language_changed,
                options={"PERSISTENT"},
            )
    except Exception:
        logger.debug("Mixar translations: msgbus subscription failed", exc_info=True)


def _on_load_post(*_args) -> None:
    _subscribe()
    reload()


try:
    from bpy.app.handlers import persistent as _persistent
    _on_load_post = _persistent(_on_load_post)
except Exception:
    pass


def register() -> None:
    import bpy
    reload(force=True)
    api.set_ui_locale(_interface_locale())
    _subscribe()
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)
    if not bpy.app.timers.is_registered(_poll_locale):
        bpy.app.timers.register(_poll_locale, first_interval=_POLL_INTERVAL_S,
                                persistent=True)


def unregister() -> None:
    import bpy
    try:
        if _on_load_post in bpy.app.handlers.load_post:
            bpy.app.handlers.load_post.remove(_on_load_post)
    except Exception:
        pass
    try:
        if bpy.app.timers.is_registered(_poll_locale):
            bpy.app.timers.unregister(_poll_locale)
    except Exception:
        pass
    try:
        bpy.msgbus.clear_by_owner(_MSGBUS_OWNER)
    except Exception:
        pass
    _unregister_dict()
    _state.update(code=None, locale=None)
    api.set_ui_locale(SOURCE_LOCALE)
