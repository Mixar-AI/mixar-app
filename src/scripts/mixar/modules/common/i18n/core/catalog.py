# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Locale resolution and the translation dictionary Blender is handed.

Pure Python (no ``bpy``) so it is unit-testable; ``runtime.py`` wires it to
``bpy.app.translations``.
"""

from __future__ import annotations

from pathlib import Path

from ..constants import (
    DEFAULT_CONTEXT,
    LANGUAGE_CODES,
    LOCALE_ALIASES,
    LOCALE_DIR,
    OPERATOR_CONTEXT,
    SOURCE_LOCALE,
)
from .po import load_messages


def explode_locale(locale: str) -> list[str]:
    """``sr_RS@latin`` -> ``[sr_RS@latin, sr_RS, sr@latin, sr]`` (Blender's order).

    Encoding suffixes an OS may report (``de_DE.UTF-8``) are dropped first.
    """
    base, _, variant = (locale or "").strip().partition("@")
    base = base.split(".", 1)[0]
    language, _, country = base.partition("_")
    out: list[str] = []
    for cand in (
        f"{base}@{variant}" if variant else base,
        base if variant and country else None,
        f"{language}@{variant}" if variant else None,
        language,
    ):
        if cand and cand not in out:
            out.append(cand)
    return out


def resolve_catalog_code(locale: str, available=LANGUAGE_CODES) -> str | None:
    """The shipped catalog code serving ``locale``, or None (source/unknown).

    Order: each exploded candidate as-is or through the alias table, then the
    one catalog sharing the bare language (``de_AT`` -> ``de_DE``). Any other
    English locale is the source language and gets no catalog.
    """
    available = tuple(available)
    candidates = explode_locale(locale)
    if not candidates:
        return None
    for cand in candidates:
        if cand in available:
            return cand
        alias = LOCALE_ALIASES.get(cand)
        if alias in available:
            return alias
    language = candidates[-1]
    if language == SOURCE_LOCALE.split("_", 1)[0]:
        return None
    same_language = [code for code in available
                     if "@" not in code and code.split("_", 1)[0] == language]
    if len(same_language) == 1:
        return same_language[0]
    return None


def catalog_path(code: str, locale_dir: Path = LOCALE_DIR) -> Path:
    return Path(locale_dir) / f"{code}.po"


def build_translation_dict(messages: dict) -> dict[tuple[str, str], str]:
    """Blender-shaped ``{(context, msgid): translation}`` for one locale.

    Default-context entries are registered under ``"*"`` AND ``"Operator"``:
    ``layout.operator(text=...)`` translates its label in the operator
    type's context, so the same UI string must resolve in both.
    """
    out: dict[tuple[str, str], str] = {}
    for (ctxt, msgid), msgstr in messages.items():
        if ctxt in (None, "", DEFAULT_CONTEXT):
            out[(DEFAULT_CONTEXT, msgid)] = msgstr
            out.setdefault((OPERATOR_CONTEXT, msgid), msgstr)
        else:
            out[(ctxt, msgid)] = msgstr
    # An explicit Operator-context translation must win over the mirrored one.
    for (ctxt, msgid), msgstr in messages.items():
        if ctxt == OPERATOR_CONTEXT:
            out[(OPERATOR_CONTEXT, msgid)] = msgstr
    return out


def load_locale(locale: str, locale_dir: Path = LOCALE_DIR) -> tuple[str | None, dict]:
    """``(catalog_code, translation_dict)`` for ``locale``; empty when none."""
    available = tuple(code for code in LANGUAGE_CODES
                      if catalog_path(code, locale_dir).is_file())
    code = resolve_catalog_code(locale, available)
    if code is None:
        return None, {}
    return code, build_translation_dict(load_messages(catalog_path(code, locale_dir)))
