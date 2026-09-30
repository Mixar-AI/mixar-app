# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Constants for Mixar's interface translations.

Translations ride on Blender's own mechanism: the active locale's catalog is
registered with ``bpy.app.translations``, which is also the fallback that C++
``IFACE_``/``TIP_``/``RPT_`` lookups consult after Blender's ``blender.mo``.
One catalog therefore serves Python panels, operators, reports and the native
C++ editors alike.
"""

from pathlib import Path

# Owner key passed to ``bpy.app.translations.register``.
TRANSLATIONS_OWNER = "mixar"

# Catalogs live next to this file: ``locale/<code>.po`` plus the ``mixar.pot``
# template the extractor writes.
LOCALE_DIR = Path(__file__).resolve().parent / "locale"
TEMPLATE_NAME = "mixar.pot"

# Source language of every msgid.
SOURCE_LOCALE = "en_US"

# Blender's default context. ``None``/``""``/``"*"`` all resolve to it.
DEFAULT_CONTEXT = "*"
# ``layout.operator(text=...)`` and operator names translate in this context
# (``BLT_I18NCONTEXT_OPERATOR_DEFAULT``); default-context entries are also
# registered under it so an operator button finds the same string.
OPERATOR_CONTEXT = "Operator"

# Every language Blender 5.2 ships (``locale/languages`` of the pinned
# upstream), minus English (US), the source. ``(code, english_name)``; the code
# is the exact locale string ``bpy.app.translations.locale`` reports and the
# catalog's file stem.
LANGUAGES = (
    ("ab", "Abkhaz"),
    ("ar_EG", "Arabic"),
    ("eu_EU", "Basque"),
    ("be", "Belarusian"),
    ("bg_BG", "Bulgarian"),
    ("ca_AD", "Catalan"),
    ("zh_HANS", "Chinese (Simplified)"),
    ("zh_HANT", "Chinese (Traditional)"),
    ("hr", "Croatian"),
    ("cs_CZ", "Czech"),
    ("da", "Danish"),
    ("nl_NL", "Dutch"),
    ("en_GB", "English (UK)"),
    ("eo", "Esperanto"),
    ("fi_FI", "Finnish"),
    ("fr_FR", "French"),
    ("ka", "Georgian"),
    ("de_DE", "German"),
    ("el_GR", "Greek"),
    ("he_IL", "Hebrew"),
    ("hi_IN", "Hindi"),
    ("hu_HU", "Hungarian"),
    ("id_ID", "Indonesian"),
    ("it_IT", "Italian"),
    ("ja_JP", "Japanese"),
    ("ko_KR", "Korean"),
    ("ky_KG", "Kyrgyz"),
    ("lt", "Lithuanian"),
    ("ml", "Malayalam"),
    ("nb", "Norwegian (Bokmål)"),
    ("fa_IR", "Persian"),
    ("pl_PL", "Polish"),
    ("pt_BR", "Portuguese (Brazil)"),
    ("pt_PT", "Portuguese (Portugal)"),
    ("ro_RO", "Romanian"),
    ("ru_RU", "Russian"),
    ("sr_RS", "Serbian (Cyrillic)"),
    ("sr_RS@latin", "Serbian (Latin)"),
    ("sk_SK", "Slovak"),
    ("sl", "Slovenian"),
    ("es", "Spanish"),
    ("sw", "Swahili"),
    ("sv_SE", "Swedish"),
    ("ta", "Tamil"),
    ("th_TH", "Thai"),
    ("tr_TR", "Turkish"),
    ("uk_UA", "Ukrainian"),
    ("ur", "Urdu"),
    ("vi_VN", "Vietnamese"),
)

LANGUAGE_CODES = tuple(code for code, _name in LANGUAGES)

# Locales an OS can report under "Automatic" that do not explode onto one of
# the codes above (Blender's own catalogs use the same script-based Chinese
# codes). Checked after the exact/exploded candidates, before the bare
# language fallback.
LOCALE_ALIASES = {
    "zh_CN": "zh_HANS",
    "zh_SG": "zh_HANS",
    "zh_Hans": "zh_HANS",
    "zh_TW": "zh_HANT",
    "zh_HK": "zh_HANT",
    "zh_MO": "zh_HANT",
    "zh_Hant": "zh_HANT",
    "pt": "pt_PT",
    "sr@latin": "sr_RS@latin",
    "sr_Latn": "sr_RS@latin",
    "nn": "nb",
    "no": "nb",
    "iw": "he_IL",
    "in": "id_ID",
}
