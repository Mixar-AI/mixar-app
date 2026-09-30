# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""One splash choice for the UI, narration and English-timed subtitles.

Historical tour codes remain valid, but every shipped UI locale has its own
choice (including regional/script variants). Only NARRATION_CODES have video
packs. Blender preferences are authoritative once available; the per-user
config preserves a splash choice even before Continue saves preferences.
"""

import os
from dataclasses import dataclass
from typing import Callable, Optional

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n.constants import LANGUAGES as UI_LANGUAGES
from mixar.modules.common.i18n.core.catalog import resolve_catalog_code

logger = get_logger(__name__)

CONFIG_KEY = "tour_language"
ENV_LANGUAGE = "MIXAR_TOUR_LANG"
DEFAULT_CODE = "en"


@dataclass(frozen=True)
class Language:
    code: str
    label: str
    english: str
    locale: str


# Retain the original numeric enum values and CDN identifiers.
_DUBBED = (
    Language("en", "English", "English", "en_US"),
    Language("zh", "简体中文", "Chinese (Simplified)", "zh_HANS"),
    Language("ko", "한국어", "Korean", "ko_KR"),
    Language("ja", "日本語", "Japanese", "ja_JP"),
    Language("ar", "ﺔﻴﺑﺮﻌﻟﺍ", "Arabic", "ar_EG"),
    Language("fr", "Français", "French", "fr_FR"),
    Language("de", "Deutsch", "German", "de_DE"),
    Language("es", "Español", "Spanish", "es"),
    Language("it", "Italiano", "Italian", "it_IT"),
    Language("pt", "Português (Portugal)", "Portuguese (Portugal)", "pt_PT"),
)
_NATIVE_NAMES = {
    "ab": "Аҧсуа", "eu_EU": "Euskara", "be": "Беларуская",
    "bg_BG": "Български", "ca_AD": "Català", "zh_HANT": "繁體中文",
    "hr": "Hrvatski", "cs_CZ": "Čeština", "da": "Dansk", "nl_NL": "Nederlands",
    "en_GB": "English (UK)", "eo": "Esperanto", "fi_FI": "Suomi",
    "ka": "ქართული", "el_GR": "Ελληνικά", "he_IL": "תירבע", "hi_IN": "हिन्दी",
    "hu_HU": "Magyar", "id_ID": "Bahasa Indonesia", "ky_KG": "Кыргызча",
    "lt": "Lietuvių", "ml": "മലയാളം", "nb": "Norsk bokmål", "fa_IR": "ﯽﺳﺭﺎﻓ",
    "pl_PL": "Polski", "pt_BR": "Português (Brasil)", "ro_RO": "Română",
    "ru_RU": "Русский", "sr_RS": "Српски", "sr_RS@latin": "Srpski",
    "sk_SK": "Slovenčina", "sl": "Slovenščina", "sw": "Kiswahili",
    "sv_SE": "Svenska", "ta": "தமிழ்", "th_TH": "ไทย", "tr_TR": "Türkçe",
    "uk_UA": "Українська", "ur": "ﻭﺩﺭﺍ", "vi_VN": "Tiếng Việt",
}
_DUBBED_LOCALES = {lang.locale for lang in _DUBBED}
LANGUAGES = _DUBBED + tuple(
    Language(locale, _NATIVE_NAMES[locale], english, locale)
    for locale, english in UI_LANGUAGES if locale not in _DUBBED_LOCALES
)
CODES = tuple(lang.code for lang in LANGUAGES)
NARRATION_CODES = tuple(lang.code for lang in _DUBBED)
_BY_CODE = {lang.code: lang for lang in LANGUAGES}
_BY_LOCALE = {lang.locale: lang.code for lang in LANGUAGES}


def normalize(code) -> str:
    """Keep UI variants distinct while accepting old tour codes/locales."""
    if not isinstance(code, str) or not code.strip():
        return DEFAULT_CODE
    code = code.strip().replace("-", "_")
    if code in _BY_CODE:
        return code
    if code in _BY_LOCALE:
        return _BY_LOCALE[code]
    locale = resolve_catalog_code(code)
    return _BY_LOCALE.get(locale, DEFAULT_CODE)


def narration_code(code: str) -> Optional[str]:
    """CDN code, English, or None when this is a subtitles-only language."""
    code = normalize(code)
    return {"en_GB": "en", "zh_HANT": "zh", "pt_BR": "pt"}.get(
        code, code if code in NARRATION_CODES else None)


def subtitle_code(code: str) -> str:
    code = normalize(code)
    return "en" if code == "en_GB" else code


def selection() -> str:
    """Current UI choice, with config fallback outside Blender."""
    try:
        import bpy
        view = bpy.context.preferences.view
        locale = view.language
        if locale == "DEFAULT":
            locale = bpy.app.translations.locale
        if isinstance(locale, str):
            return normalize(locale)
    except Exception:
        pass
    return stored()


def get(code: str) -> Language:
    return _BY_CODE[normalize(code)]


def is_bundled(code: str) -> bool:
    """Whether the selected voice is bundled (English US/UK)."""
    return narration_code(code) == DEFAULT_CODE


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
    """QA override, then the current interface selection."""
    return resolve(os.environ.get(ENV_LANGUAGE), selection())


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
    from .language_preferences import apply_interface
    apply_interface(code)
    for fn in list(_listeners):
        try:
            fn(code)
        except Exception as exc:  # noqa: BLE001
            logger.debug("tour language: listener %r failed: %s", fn, exc)
    return code
