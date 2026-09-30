#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Validate the language catalogs against the template and report coverage.

Errors (exit 1):
* a Blender language without a catalog, or a catalog for no language
* a catalog whose messages differ from ``mixar.pot`` (run update_catalogs.py);
  a sparse catalog (``en_GB``) may hold a subset, in template order, of
  entries that change the text
* a translation that changes placeholders: ``{name}`` fields for Python
  messages, the ``%`` conversion sequence for C/C++ messages (printf cannot
  reorder arguments on every platform), or a trailing newline

Coverage is reported per language; ``--min-coverage`` turns a shortfall into
an error.

Usage:
    python3 scripts/i18n/check_catalogs.py [--min-coverage 100] [--quiet]
"""

from __future__ import annotations

import argparse
import re
import string
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from i18n_common import SPARSE_CATALOGS, load_runtime_package  # noqa: E402

PRINTF = re.compile(r"%(?:%|[-+ #0']*(?:\d+|\*)?(?:\.(?:\d+|\*))?"
                    r"(?:hh|h|ll|l|L|z|j|t|I64|I32)?[diouxXeEfFgGaAcspn])")


def brace_fields(text: str) -> Counter | None:
    """Replacement fields of a ``str.format`` template (None if not one)."""
    try:
        parsed = list(string.Formatter().parse(text))
    except ValueError:
        return None
    return Counter(f"{{{name}{':' + spec if spec else ''}}}" for _lit, name, spec, _conv in parsed
                   if name is not None)


def printf_fields(text: str) -> list[str]:
    return PRINTF.findall(text)


def placeholder_errors(msgid: str, msgstr: str, languages: set[str]) -> list[str]:
    errors = []
    if "python" in languages:
        want = brace_fields(msgid)
        if want is not None and want:
            got = brace_fields(msgstr)
            if got != want:
                errors.append(f"placeholders {sorted(want)} became {sorted(got or [])}")
    if "c" in languages:
        want = printf_fields(msgid)
        if want and printf_fields(msgstr) != want:
            errors.append(f"printf sequence {want} became {printf_fields(msgstr)}")
    if msgid.endswith("\n") != msgstr.endswith("\n"):
        errors.append("trailing newline differs")
    return errors


def source_languages(entry) -> set[str]:
    out = set()
    for ref in entry.references:
        out.add("python" if ref.endswith(".py") else "c")
    return out or {"python", "c"}


def check(constants, po, min_coverage: float | None = None, quiet: bool = False) -> int:
    locale_dir = constants.LOCALE_DIR
    template = [e for e in po.read_po(locale_dir / constants.TEMPLATE_NAME) if not e.is_header]
    keys = [e.key for e in template]
    position = {key: i for i, key in enumerate(keys)}
    langs_of = {e.key: source_languages(e) for e in template}
    errors: list[str] = []

    present = {p.stem for p in locale_dir.glob("*.po")}
    for code in sorted(set(constants.LANGUAGE_CODES) - present):
        errors.append(f"{code}: catalog missing")
    for code in sorted(present - set(constants.LANGUAGE_CODES)):
        errors.append(f"{code}.po: not a Blender language")

    rows = []
    for code in constants.LANGUAGE_CODES:
        path = locale_dir / f"{code}.po"
        if not path.is_file():
            continue
        entries = po.read_po(path)
        header = po.header_fields(entries)
        if header.get("Language") != code:
            errors.append(f"{code}: header Language is {header.get('Language')!r}")
        body = [e for e in entries if not e.is_header and not e.obsolete]
        sparse = code in SPARSE_CATALOGS
        if sparse:
            order = [position.get(e.key) for e in body]
            if None in order or order != sorted(order):
                errors.append(f"{code}: messages not in mixar.pot or out of its order "
                              "(run update_catalogs.py)")
            for e in body:
                if not e.msgstr or e.msgstr == e.msgid:
                    errors.append(f"{code}: {e.msgid!r}: a sparse catalog holds only changed text")
        elif [e.key for e in body] != keys:
            errors.append(f"{code}: messages differ from mixar.pot (run update_catalogs.py)")
        done = 0
        for e in body:
            if not e.msgstr or e.fuzzy:
                continue
            done += 1
            for problem in placeholder_errors(e.msgid, e.msgstr, langs_of.get(e.key, set())):
                errors.append(f"{code}: {e.msgid!r}: {problem}")
        if sparse:
            rows.append((code, done, None))
            continue
        coverage = 100.0 * done / len(keys) if keys else 100.0
        rows.append((code, done, coverage))
        if min_coverage is not None and coverage + 1e-9 < min_coverage:
            errors.append(f"{code}: {coverage:.1f}% translated, below {min_coverage}%")

    if not quiet:
        for code, done, coverage in rows:
            if coverage is None:
                print(f"{code:12s} {done:6d} differ from the source (sparse)")
            else:
                print(f"{code:12s} {done:6d}/{len(keys)}  {coverage:5.1f}%")
    for err in errors:
        print("ERROR:", err)
    return 1 if errors else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--min-coverage", type=float, default=None)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    constants, po = load_runtime_package()
    return check(constants, po, args.min_coverage, args.quiet)


if __name__ == "__main__":
    sys.exit(main())
