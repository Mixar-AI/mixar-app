#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Merge ``locale/mixar.pot`` into every language catalog.

Each ``locale/<code>.po`` ends up with exactly the template's messages, in the
template's order: existing translations are kept, new messages arrive
untranslated (English at runtime until translated) and messages the code no
longer has are dropped. Catalogs carry no source references — the template
has them — which keeps 49 files small.

``--prefill-blender DIR`` fills untranslated messages from Blender's own
catalogs (``DIR/<lang>.po``, the pinned upstream's ``locale/po``): the same
string in the default context first, then as an operator name. Blender's
wording is what the rest of the interface already uses.

Usage:
    python3 scripts/i18n/update_catalogs.py
    python3 scripts/i18n/update_catalogs.py --prefill-blender upstream/locale/po
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from i18n_common import SPARSE_CATALOGS, load_runtime_package  # noqa: E402

TEAM = "Mixar (machine-translated, native review welcome)"
# REUSE metadata in every catalog's header comment (``reuse lint`` runs on PRs).
# REUSE-IgnoreStart
SPDX = ["SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited",
        "SPDX-License-Identifier: GPL-3.0-or-later"]
# REUSE-IgnoreEnd


def language_header(po, code: str, name: str):
    return po.PoEntry(msgid="", msgstr=(
        "Project-Id-Version: Mixar\n"
        f"Language-Team: {TEAM}\n"
        f"Language: {code}\n"
        "MIME-Version: 1.0\n"
        "Content-Type: text/plain; charset=UTF-8\n"
        "Content-Transfer-Encoding: 8bit\n"
        f"X-Mixar-Language-Name: {name}\n"
    ), comments=["Mixar interface translations.",
                 "This file is distributed under the same license as the Mixar package.",
                 "", *SPDX])


def blender_catalog(po, catalog, blender_dir: Path, code: str) -> dict:
    """``{(ctxt, msgid): msgstr}`` of Blender's catalog serving ``code``."""
    for cand in catalog.explode_locale(code):
        path = blender_dir / f"{cand}.po"
        if path.is_file():
            return po.load_messages(path)
    return {}


def merge(template, existing: dict, po, blender: dict | None = None):
    """Template entries carrying the catalog's translations (+ prefill)."""
    out = []
    prefilled = 0
    for entry in template:
        if entry.is_header:
            continue
        old = existing.get(entry.key)
        new = po.PoEntry(msgid=entry.msgid, msgctxt=entry.msgctxt)
        if old is not None and old.msgstr:
            new.msgstr = old.msgstr
            new.flags = set(old.flags) & {"fuzzy"}
            new.comments = list(old.comments)
        elif blender:
            for key in (entry.key, (None, entry.msgid), ("Operator", entry.msgid)):
                value = blender.get(key)
                if value:
                    new.msgstr = value
                    prefilled += 1
                    break
        out.append(new)
    return out, prefilled


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--prefill-blender", type=Path, default=None, metavar="DIR",
                        help="Blender's locale/po directory to prefill untranslated messages")
    parser.add_argument("--languages", nargs="*", default=None,
                        help="only these catalog codes (default: all)")
    args = parser.parse_args(argv)

    constants, po = load_runtime_package()
    import importlib
    catalog = importlib.import_module("mixar_i18n.core.catalog")

    template_path = constants.LOCALE_DIR / constants.TEMPLATE_NAME
    if not template_path.is_file():
        print("update_catalogs: no template, run extract_messages.py first", file=sys.stderr)
        return 2
    template = po.read_po(template_path)
    total = sum(1 for e in template if not e.is_header)
    names = dict(constants.LANGUAGES)
    for code in args.languages or constants.LANGUAGE_CODES:
        path = constants.LOCALE_DIR / f"{code}.po"
        existing = {}
        if path.is_file():
            existing = {e.key: e for e in po.read_po(path) if not e.is_header and not e.obsolete}
        blender = blender_catalog(po, catalog, args.prefill_blender, code) \
            if args.prefill_blender else None
        entries, prefilled = merge(template, existing, po, blender)
        if code in SPARSE_CATALOGS:
            # derive_catalogs.py fills these from the template; keep only real differences.
            entries = [e for e in entries if e.msgstr and e.msgstr != e.msgid]
        po.write_po(path, [language_header(po, code, names[code])] + entries)
        done = sum(1 for e in entries if e.msgstr and not e.fuzzy)
        extra = f", {prefilled} prefilled from Blender" if prefilled else ""
        print(f"{code:12s} {done:6d}/{total} translated{extra}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
