# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mixar interface translations (every language Blender ships).

``iface_``/``tip_``/``rpt_``/``data_`` translate runtime-built or hand-drawn
text, ``n_`` marks constants for extraction. Catalogs are
``locale/<code>.po``; ``scripts/i18n`` extracts, merges and checks them. See
``core/api.py`` for which strings need a helper and which Blender translates
by itself.
"""

from .constants import LANGUAGE_CODES, LANGUAGES
from .core.api import (
    current_locale,
    data_,
    iface_,
    interface_translated,
    n_,
    rpt_,
    tip_,
    ui_locale,
)

__all__ = [
    "LANGUAGES",
    "LANGUAGE_CODES",
    "current_locale",
    "data_",
    "iface_",
    "interface_translated",
    "n_",
    "rpt_",
    "tip_",
    "ui_locale",
]
