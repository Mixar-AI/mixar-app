#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hand untranslated messages to a translator (human or model) and take them back.

``export`` writes one catalog's untranslated messages as JSON batches,
``<code>.<n>.json``::

    {"language": "de_DE", "items": [
        {"id": 0, "msgid": "Bake Textures", "ctxt": null, "kind": "label", "file": "bake_ops.py"},
        ...]}

A translator answers each batch with ``<code>.<n>.out.json``, a map from item
id to translation (``{"0": "Texturen backen", ...}``; an empty string means
"leave untranslated"). ``validate`` checks answers without touching the
catalog; ``import`` merges every translation whose placeholders survive (the
``check_catalogs`` rules) and prints the rejected ones. Answers are written in
normal logical order; for the right-to-left languages ``import`` converts them
to the visual, pre-shaped form Blender's text engine needs (``rtl.py``).

Usage:
    python3 scripts/i18n/translation_batches.py export de_DE --out /tmp/de --size 600
    python3 scripts/i18n/translation_batches.py validate /tmp/de/de_DE.*.out.json
    python3 scripts/i18n/translation_batches.py import /tmp/de/de_DE.*.out.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_catalogs import placeholder_errors, source_languages  # noqa: E402
from i18n_common import load_runtime_package  # noqa: E402
from rtl import RTL_LANGUAGES, log2vis  # noqa: E402


def _template(constants, po):
    return {e.key: e for e in po.read_po(constants.LOCALE_DIR / constants.TEMPLATE_NAME)
            if not e.is_header}


def export(constants, po, code: str, out: Path, size: int, retranslate: bool = False) -> int:
    template = _template(constants, po)
    catalog = po.read_po(constants.LOCALE_DIR / f"{code}.po")
    pending = [e for e in catalog if not e.is_header and (retranslate or not e.msgstr or e.fuzzy)]
    out.mkdir(parents=True, exist_ok=True)
    count = 0
    for start in range(0, len(pending), size):
        items = []
        for offset, entry in enumerate(pending[start:start + size]):
            source = template.get(entry.key)
            items.append({
                "id": offset,
                "msgid": entry.msgid,
                "ctxt": entry.msgctxt,
                "kind": source.extracted[0] if source and source.extracted else "",
                "file": Path(source.references[0]).name if source and source.references else "",
            })
        path = out / f"{code}.{count:03d}.json"
        # One item per line: compact for a model translator, readable for a human.
        lines = ",\n".join(json.dumps(item, ensure_ascii=False) for item in items)
        path.write_text(f'{{"language": "{code}", "items": [\n{lines}\n]}}\n', encoding="utf-8")
        count += 1
    print(f"{code}: {len(pending)} messages in {count} batch(es) under {out}")
    return 0


def _answers(out_file: Path):
    """``(language, [(item, msgstr)])`` of one answered batch."""
    batch_file = Path(str(out_file).replace(".out.json", ".json"))
    batch = json.loads(batch_file.read_text(encoding="utf-8"))
    answers = json.loads(out_file.read_text(encoding="utf-8"))
    by_id = {str(item["id"]): item for item in batch["items"]}
    pairs = [(by_id.get(str(key)), value) for key, value in answers.items()]
    missing = [item for key, item in by_id.items() if key not in answers]
    return batch["language"], pairs, missing


def _problems(item, msgstr, template) -> list[str]:
    if item is None:
        return ["unknown id"]
    if not isinstance(msgstr, str):
        return ["translation is not a string"]
    if not msgstr.strip():
        return []
    key = (item.get("ctxt"), item["msgid"])
    langs = source_languages(template[key]) if key in template else {"python", "c"}
    return placeholder_errors(item["msgid"], msgstr, langs)


def validate(constants, po, files: list[Path]) -> int:
    template = _template(constants, po)
    bad = 0
    for out_file in files:
        _language, pairs, missing = _answers(out_file)
        for item, msgstr in pairs:
            for problem in _problems(item, msgstr, template):
                bad += 1
                msgid = item["msgid"] if item else "?"
                print(f"{out_file.name}: {msgid!r} -> {msgstr!r}: {problem}")
        if missing:
            bad += len(missing)
            print(f"{out_file.name}: {len(missing)} item(s) without an answer, "
                  f"e.g. ids {[item['id'] for item in missing[:5]]}")
    print("OK" if not bad else f"{bad} problem(s)")
    return 1 if bad else 0


def import_batches(constants, po, files: list[Path], overwrite: bool = False) -> int:
    template = _template(constants, po)
    by_language: dict = {}
    for out_file in files:
        language, pairs, _missing = _answers(out_file)
        by_language.setdefault(language, []).extend(pairs)
    for language, pairs in sorted(by_language.items()):
        path = constants.LOCALE_DIR / f"{language}.po"
        entries = po.read_po(path)
        by_key = {e.key: e for e in entries if not e.is_header}
        merged = rejected = 0
        for item, msgstr in pairs:
            if item is None or not isinstance(msgstr, str) or not msgstr.strip():
                continue
            entry = by_key.get((item.get("ctxt"), item["msgid"]))
            if entry is None or (entry.msgstr and not entry.fuzzy and not overwrite):
                continue
            problems = _problems(item, msgstr, template)
            if not problems and language in RTL_LANGUAGES:
                # Stored in Blender's visual, pre-shaped form (see rtl.py).
                msgstr = log2vis(msgstr)
                problems = _problems(item, msgstr, template)
            if problems:
                rejected += 1
                print(f"{language}: rejected {item['msgid']!r} -> {msgstr!r}: {'; '.join(problems)}")
                continue
            entry.msgstr = msgstr
            entry.flags.discard("fuzzy")
            merged += 1
        po.write_po(path, entries)
        print(f"{language}: merged {merged}, rejected {rejected}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    exp = sub.add_parser("export")
    exp.add_argument("language")
    exp.add_argument("--out", type=Path, required=True)
    exp.add_argument("--size", type=int, default=600)
    exp.add_argument("--all", action="store_true", help="include translated messages too")
    val = sub.add_parser("validate")
    val.add_argument("files", nargs="+", type=Path)
    imp = sub.add_parser("import")
    imp.add_argument("files", nargs="+", type=Path)
    imp.add_argument("--overwrite", action="store_true",
                     help="replace existing translations as well")
    args = parser.parse_args(argv)

    constants, po = load_runtime_package()
    if args.command == "export":
        if args.language not in constants.LANGUAGE_CODES:
            print(f"unknown language {args.language!r}", file=sys.stderr)
            return 2
        return export(constants, po, args.language, args.out, args.size, args.all)
    if args.command == "validate":
        return validate(constants, po, args.files)
    return import_batches(constants, po, args.files, args.overwrite)


if __name__ == "__main__":
    sys.exit(main())
