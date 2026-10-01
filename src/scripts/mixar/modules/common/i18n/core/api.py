# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Translation helpers for text Blender does not translate on its own.

Blender already translates STATIC strings it is handed: ``bl_label``,
``bl_description``, property/enum names and descriptions, ``text=`` of
``layout`` calls and ``Operator.report`` messages. Use these helpers only for
what it cannot see:

* text drawn by hand (``blf``/GPU overlays, custom widgets)
* labels assembled at runtime — translate the TEMPLATE, then format:
  ``iface_("{count} jobs running").format(count=n)``; pass the result with
  ``translate=False`` where the layout call would translate it again
* UI strings kept in module-level constants: mark them with ``n_()`` so the
  extractor finds them, translate with ``iface_()`` where they are drawn

``iface_`` is interface text (labels, buttons, headings), ``tip_`` tooltips
and descriptions, ``rpt_`` report/notification messages, ``data_`` names of
new data-blocks. All return the msgid unchanged when translation is off, the
catalog has no entry, or ``bpy`` is unavailable (tests, headless workers).
Never pass user data (object names, prompts, server text) through them.
"""

from __future__ import annotations

_translations = None
# The UI locale as last seen on the main thread (``runtime`` keeps it
# current). ``bpy.app.translations.locale`` reports ``en_US`` off the main
# thread, and requests are made from worker threads.
_ui_locale = "en_US"


def _module():
    global _translations
    if _translations is None:
        try:
            from bpy.app import translations
        except Exception:
            return None
        _translations = translations
    return _translations


def _call(name: str, msgid, msgctxt):
    if not isinstance(msgid, str) or not msgid:
        return msgid
    module = _module()
    if module is None:
        return msgid
    try:
        if msgctxt is None:
            out = getattr(module, name)(msgid)
        else:
            out = getattr(module, name)(msgid, msgctxt)
    except Exception:
        return msgid
    return out if isinstance(out, str) else msgid


def iface_(msgid: str, msgctxt: str | None = None) -> str:
    """Interface text (labels, buttons, headings, drawn captions)."""
    return _call("pgettext_iface", msgid, msgctxt)


def tip_(msgid: str, msgctxt: str | None = None) -> str:
    """Tooltip / description text."""
    return _call("pgettext_tip", msgid, msgctxt)


def rpt_(msgid: str, msgctxt: str | None = None) -> str:
    """Report, toast and status messages."""
    return _call("pgettext_rpt", msgid, msgctxt)


def data_(msgid: str, msgctxt: str | None = None) -> str:
    """Default names of newly created data-blocks."""
    return _call("pgettext_data", msgid, msgctxt)


def n_(msgid: str, msgctxt: str | None = None) -> str:
    """Mark ``msgid`` for extraction without translating it (translate later)."""
    return msgid


def current_locale() -> str:
    """The resolved UI locale (``en_US`` when translation is off/unavailable)."""
    module = _module()
    if module is None:
        return "en_US"
    try:
        locale = module.locale
    except Exception:
        return "en_US"
    return locale if isinstance(locale, str) and locale else "en_US"


def ui_locale() -> str:
    """The locale the interface is shown in (``en_US`` when not translated).

    Thread-safe: what the backend is told as ``X-Mixar-Locale``.
    """
    return _ui_locale


def set_ui_locale(locale: str) -> None:
    global _ui_locale
    _ui_locale = locale or "en_US"


def interface_translated() -> bool:
    """True when Blender's interface-translation option is active."""
    try:
        import bpy
        view = bpy.context.preferences.view
        return bool(view.use_translate_interface) and current_locale() != "en_US"
    except Exception:
        return False
