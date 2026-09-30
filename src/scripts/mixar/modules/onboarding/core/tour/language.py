# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — the language model.

One ordered table of the languages the tour can be narrated in. It is the
single source for the first-time splash dropdown, the pack codes on the
CDN, the subtitle filenames under ``assets/tour/subtitles/`` and the
telemetry ``language`` property. English is bundled; every other language
is a downloadable pack, and until the pack is complete the English video
plays with that language's subtitles.

Resolution order (``current()``): the ``MIXAR_TOUR_LANG`` environment
variable (QA harness) → the persisted per-user choice
(``tour_language`` in the user ``mixar.json`` overlay) → English.

This module never imports ``bpy``; the WindowManager property that shows
the dropdown lives in ``ui/properties/tour_props.py`` and calls in here.
The choice is deliberately independent of Blender's ``view.language``:
Mixar's own UI strings are not translated yet, and a dropdown that
switched half the interface would read as broken.
"""

import os
from dataclasses import dataclass
from typing import Callable, Optional

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

CONFIG_KEY = "tour_language"
ENV_LANGUAGE = "MIXAR_TOUR_LANG"
DEFAULT_CODE = "en"


@dataclass(frozen=True)
class Language:
    code: str        # pack code, subtitle filename, telemetry value
    label: str       # native name shown in the dropdown
    english: str     # English name (dropdown description, media filenames)


# Display order is a product decision and is pinned by tests.
LANGUAGES = (
    Language("en", "English", "English"),
    Language("zh", "中文", "Mandarin"),
    Language("ko", "한국어", "Korean"),
    Language("ja", "日本語", "Japanese"),
    Language("ar", "العربية", "Arabic"),
    Language("fr", "Français", "French"),
    Language("de", "Deutsch", "German"),
    Language("es", "Español", "Spanish"),
    Language("it", "Italiano", "Italian"),
    Language("pt", "Português", "Portuguese"),
)

CODES = tuple(lang.code for lang in LANGUAGES)
_BY_CODE = {lang.code: lang for lang in LANGUAGES}

# Blender locale identifiers (``bpy.app.translations.locale``) that map onto
# a tour language, for callers that want to seed the choice from the UI
# locale once Mixar's interface is translated. Unlisted locales → English.
_LOCALE_ALIASES = {
    "en_US": "en", "en_GB": "en",
    "zh_HANS": "zh", "zh_CN": "zh", "zh_HANT": "zh", "zh_TW": "zh",
    "ko_KR": "ko", "ja_JP": "ja", "ar_EG": "ar",
    "fr_FR": "fr", "de_DE": "de", "es": "es", "es_ES": "es",
    "it_IT": "it", "pt_PT": "pt", "pt_BR": "pt",
}


def normalize(code) -> str:
    """A valid tour code, or English for anything unknown or empty."""
    if not isinstance(code, str) or not code:
        return DEFAULT_CODE
    code = code.strip()
    if code in _BY_CODE:
        return code
    if code in _LOCALE_ALIASES:
        return _LOCALE_ALIASES[code]
    base = code.replace("-", "_").split("_", 1)[0].lower()
    return base if base in _BY_CODE else DEFAULT_CODE


def get(code: str) -> Language:
    return _BY_CODE[normalize(code)]


def is_bundled(code: str) -> bool:
    """English ships in the build; every other language is a pack."""
    return normalize(code) == DEFAULT_CODE


def enum_items() -> tuple:
    """``(identifier, name, description)`` triples for an EnumProperty."""
    return tuple((lang.code, lang.label, lang.english) for lang in LANGUAGES)


def resolve(env_value: Optional[str], stored_value) -> str:
    """Pure resolution: the QA override wins, then the persisted choice."""
    if env_value:
        return normalize(env_value)
    return normalize(stored_value)


def stored() -> str:
    """The persisted choice (``en`` when nothing was ever chosen)."""
    try:
        from mixar.config.config import get_config
        return normalize(get_config().get(CONFIG_KEY))
    except Exception as exc:  # noqa: BLE001
        logger.debug("tour language: config read failed: %s", exc)
        return DEFAULT_CODE


def current() -> str:
    """The language the tour should play in right now."""
    return resolve(os.environ.get(ENV_LANGUAGE), stored())


# Called after every persisted change with the new code; the pack fetcher
# registers here so the download starts the moment the dropdown moves.
_listeners: list = []


def add_listener(fn: Callable[[str], None]) -> None:
    if fn not in _listeners:
        _listeners.append(fn)


def remove_listener(fn: Callable[[str], None]) -> None:
    if fn in _listeners:
        _listeners.remove(fn)


def set_stored(code: str) -> str:
    """Persist ``code`` (normalized) and notify listeners. Returns the
    normalized code. A write failure keeps the in-memory value (the
    ``add_config`` contract) and still notifies, so a pack fetch is never
    skipped because a config file was read-only."""
    code = normalize(code)
    try:
        from mixar.config.config import add_config
        if not add_config(CONFIG_KEY, code):
            logger.warning("tour language: could not persist %r", code)
    except Exception as exc:  # noqa: BLE001
        logger.warning("tour language: persist failed: %s", exc)
    for fn in list(_listeners):
        try:
            fn(code)
        except Exception as exc:  # noqa: BLE001
            logger.debug("tour language: listener %r failed: %s", fn, exc)
    return code
