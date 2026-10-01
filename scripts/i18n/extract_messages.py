#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Extract every translatable Mixar UI string into ``locale/mixar.pot``.

Scans the overlay (``src/``): Mixar Python under ``scripts/mixar`` and
``scripts/startup``, and C/C++ under ``source`` and ``intern``. A file that
overrides an upstream Blender file contributes only the messages the
upstream file does not have — those are Blender's and already translated by
its own catalogs. The upstream checkout is ``upstream/`` (or
``$MIXAR_UPSTREAM_DIR``); without it overridden files cannot be told apart,
so the run stops.

Usage:
    python3 scripts/i18n/extract_messages.py            # write the template
    python3 scripts/i18n/extract_messages.py --check    # exit 1 if stale
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import extract_cpp  # noqa: E402
import extract_python  # noqa: E402
from i18n_common import SRC_DIR, REPO_ROOT, MessageSet, default_upstream_dir, \
    load_runtime_package  # noqa: E402

PY_ROOTS = ("scripts/mixar", "scripts/startup")
CPP_ROOTS = ("source", "intern")
CPP_SUFFIXES = (".c", ".cc", ".cpp", ".h", ".hh", ".hpp", ".mm", ".m")
SKIP_DIRS = {"__pycache__", "tests", "testing", "headless", ".pytest_cache", ".venv", "venv"}

HEADER = """Mixar interface translations.
This file is distributed under the same license as the Mixar package."""


def _walk(root: Path, suffixes):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            if name.endswith(suffixes):
                yield Path(dirpath) / name


def _extract(path: Path, ref: str, contexts) -> MessageSet:
    if path.suffix == ".py":
        return extract_python.extract_file(path, ref)
    return extract_cpp.extract_file(path, ref, contexts)


def collect(upstream: Path) -> MessageSet:
    contexts = extract_cpp.load_contexts(
        upstream / "source/blender/blentranslation/BLT_translation.hh",
        SRC_DIR / "source/blender/blentranslation/BLT_translation.hh",
    )
    messages = MessageSet()
    files = [p for root in PY_ROOTS for p in _walk(SRC_DIR / root, (".py",))]
    files += [p for root in CPP_ROOTS for p in _walk(SRC_DIR / root, CPP_SUFFIXES)]
    for path in files:
        rel = path.relative_to(SRC_DIR).as_posix()
        ref = path.relative_to(REPO_ROOT).as_posix()
        upstream_file = upstream / rel
        try:
            found = _extract(path, ref, contexts)
        except SyntaxError as exc:
            raise SystemExit(f"extract_messages: cannot parse {ref}: {exc}") from exc
        if upstream_file.is_file():
            for key in _extract(upstream_file, ref, contexts).keys():
                found.discard(key)
        messages.merge(found)
    return messages


def build_template(messages: MessageSet, po):
    header = po.PoEntry(msgid="", msgstr=(
        "Project-Id-Version: Mixar\n"
        "Report-Msgid-Bugs-To: \n"
        "MIME-Version: 1.0\n"
        "Content-Type: text/plain; charset=UTF-8\n"
        "Content-Transfer-Encoding: 8bit\n"
    ), comments=HEADER.split("\n"))
    entries = [header]
    for msg in messages:
        entries.append(po.PoEntry(
            msgid=msg.msgid, msgctxt=msg.msgctxt,
            extracted=[", ".join(sorted(msg.kinds))],
            references=msg.refs,
        ))
    return entries


def _display(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--upstream", type=Path, default=None,
                        help="pinned Blender checkout (default: upstream/ or $MIXAR_UPSTREAM_DIR)")
    parser.add_argument("--check", action="store_true",
                        help="do not write; exit 1 when the template is out of date")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--list", nargs="+", type=Path, metavar="FILE",
                        help="print the messages found in these files and exit")
    args = parser.parse_args(argv)

    if args.list:
        contexts = extract_cpp.load_contexts(
            SRC_DIR / "source/blender/blentranslation/BLT_translation.hh")
        for path in args.list:
            path = path.resolve()
            for msg in _extract(path, _display(path), contexts):
                ctxt = f"[{msg.msgctxt}] " if msg.msgctxt else ""
                print(f"{_display(path)}: {ctxt}{msg.msgid!r} ({', '.join(sorted(msg.kinds))})")
        return 0

    constants, po = load_runtime_package()
    upstream = args.upstream or default_upstream_dir()
    if upstream is None:
        print("extract_messages: no upstream Blender checkout (run `make init` or set "
              "MIXAR_UPSTREAM_DIR)", file=sys.stderr)
        return 2
    messages = collect(upstream)
    text = po.format_po(build_template(messages, po))
    output = args.output or constants.LOCALE_DIR / constants.TEMPLATE_NAME
    if args.check:
        current = output.read_text(encoding="utf-8") if output.is_file() else ""
        if current != text:
            print(f"{_display(output)} is out of date: run "
                  "`make i18n_update` (scripts/i18n/extract_messages.py + update_catalogs.py)")
            return 1
        print(f"{_display(output)} is up to date ({len(messages)} messages)")
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {_display(output)}: {len(messages)} messages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
