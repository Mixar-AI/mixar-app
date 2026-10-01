#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Derive the two catalogs that are mechanical transforms of another.

* ``sr_RS@latin`` is the ``sr_RS`` (Cyrillic) catalog transliterated —
  Serbian's two scripts map letter for letter, so both stay in step.
* ``en_GB`` is the source text with British spelling (colour, centre,
  normalise, ...). It is a sparse catalog: only messages whose text changes
  are written (derived from ``mixar.pot``), the rest fall back to the
  identical source.

Only entries that are untranslated, or were derived before (translator
comment ``derived``), are written, so a hand-made translation always wins.

Usage:
    python3 scripts/i18n/derive_catalogs.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from i18n_common import load_runtime_package  # noqa: E402

DERIVED = "derived"

_SR_LATIN = {
    "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D", "Ђ": "Đ", "Е": "E", "Ж": "Ž", "З": "Z",
    "И": "I", "Ј": "J", "К": "K", "Л": "L", "Љ": "Lj", "М": "M", "Н": "N", "Њ": "Nj", "О": "O",
    "П": "P", "Р": "R", "С": "S", "Т": "T", "Ћ": "Ć", "У": "U", "Ф": "F", "Х": "H", "Ц": "C",
    "Ч": "Č", "Џ": "Dž", "Ш": "Š",
}
_SR_LATIN.update({k.lower(): v.lower() for k, v in list(_SR_LATIN.items())})


def serbian_latin(text: str) -> str:
    out = []
    for i, ch in enumerate(text):
        latin = _SR_LATIN.get(ch)
        if latin is None:
            out.append(ch)
            continue
        if len(latin) == 2 and ch.isupper():
            nxt = text[i + 1] if i + 1 < len(text) else ""
            prev = text[i - 1] if i else ""
            if nxt.isupper() or (not nxt.isalpha() and prev.isupper()):
                latin = latin.upper()
        out.append(latin)
    return "".join(out)


# US -> UK spelling of words that occur in interface text. Inflected forms are
# listed explicitly: a suffix rule would also rewrite "size", "prize", ...
_UK_WORDS = {
    "color": "colour", "colors": "colours", "colored": "coloured", "coloring": "colouring",
    "colorful": "colourful", "colorspace": "colourspace", "colorize": "colourise",
    "colorized": "colourised", "gray": "grey", "grayscale": "greyscale", "grays": "greys",
    "center": "centre", "centers": "centres", "centered": "centred", "centering": "centring",
    "normalize": "normalise", "normalized": "normalised", "normalizes": "normalises",
    "normalizing": "normalising", "normalization": "normalisation",
    "optimize": "optimise", "optimized": "optimised", "optimizes": "optimises",
    "optimizing": "optimising", "optimization": "optimisation", "optimizations": "optimisations",
    "synchronize": "synchronise", "synchronized": "synchronised", "synchronizing": "synchronising",
    "synchronization": "synchronisation",
    "customize": "customise", "customized": "customised", "customizing": "customising",
    "customization": "customisation",
    "organize": "organise", "organized": "organised", "organizing": "organising",
    "organization": "organisation", "organizations": "organisations",
    "recognize": "recognise", "recognized": "recognised", "recognizes": "recognises",
    "recognizing": "recognising", "unrecognized": "unrecognised",
    "initialize": "initialise", "initialized": "initialised", "initializing": "initialising",
    "initialization": "initialisation", "uninitialized": "uninitialised",
    "finalize": "finalise", "finalized": "finalised", "finalizing": "finalising",
    "visualize": "visualise", "visualized": "visualised", "visualization": "visualisation",
    "visualizations": "visualisations",
    "minimize": "minimise", "minimized": "minimised", "minimizing": "minimising",
    "maximize": "maximise", "maximized": "maximised", "maximizing": "maximising",
    "authorize": "authorise", "authorized": "authorised", "authorizing": "authorising",
    "authorization": "authorisation", "unauthorized": "unauthorised",
    "prioritize": "prioritise", "prioritized": "prioritised", "categorize": "categorise",
    "categorized": "categorised", "summarize": "summarise", "summarized": "summarised",
    "stylize": "stylise", "stylized": "stylised", "randomize": "randomise",
    "randomized": "randomised", "randomizes": "randomises", "serialize": "serialise",
    "serialized": "serialised", "realize": "realise", "realized": "realised",
    "utilize": "utilise", "utilization": "utilisation", "specialized": "specialised",
    "materialize": "materialise", "rasterize": "rasterise", "rasterized": "rasterised",
    "symmetrize": "symmetrise", "sanitize": "sanitise",
    "sanitized": "sanitised", "apologize": "apologise", "emphasize": "emphasise",
    "favorite": "favourite", "favorites": "favourites", "favorited": "favourited",
    "behavior": "behaviour", "behaviors": "behaviours", "neighbor": "neighbour",
    "neighbors": "neighbours", "neighboring": "neighbouring",
    "analyze": "analyse", "analyzed": "analysed", "analyzes": "analyses", "analyzing": "analysing",
    "catalog": "catalogue", "catalogs": "catalogues",
    "canceled": "cancelled", "canceling": "cancelling", "labeled": "labelled",
    "labeling": "labelling", "modeling": "modelling", "modeled": "modelled",
    "modeler": "modeller", "traveled": "travelled", "traveling": "travelling",
    "leveled": "levelled", "leveling": "levelling", "signaled": "signalled",
    "fulfill": "fulfil", "enrollment": "enrolment",
    "meter": "metre", "meters": "metres", "millimeter": "millimetre", "millimeters": "millimetres",
    "centimeter": "centimetre", "centimeters": "centimetres", "kilometer": "kilometre",
    "kilometers": "kilometres", "liter": "litre", "liters": "litres",
    "aluminum": "aluminium", "mold": "mould", "molds": "moulds", "jewelry": "jewellery",
    "theater": "theatre", "fiber": "fibre", "fibers": "fibres",
}
_UK_WORD = re.compile(r"\b(" + "|".join(sorted(_UK_WORDS, key=len, reverse=True)) + r")\b",
                      re.IGNORECASE)
_PLACEHOLDER = re.compile(r"\{[^{}]*\}|%[-+ #0]*\d*(?:\.\d+)?[a-zA-Z]")


def _match_case(word: str, repl: str) -> str:
    if word.isupper():
        return repl.upper()
    if word[0].isupper():
        return repl[0].upper() + repl[1:]
    return repl


def british(text: str) -> str:
    # Placeholders are code (``{color}``); only the prose between them changes.
    parts = []
    last = 0
    for m in _PLACEHOLDER.finditer(text):
        parts.append(_UK_WORD.sub(lambda w: _match_case(w.group(0), _UK_WORDS[w.group(0).lower()]),
                                  text[last:m.start()]))
        parts.append(m.group(0))
        last = m.end()
    parts.append(_UK_WORD.sub(lambda w: _match_case(w.group(0), _UK_WORDS[w.group(0).lower()]),
                              text[last:]))
    return "".join(parts)


def _derive(po, target_path: Path, value_for) -> tuple[int, int]:
    entries = po.read_po(target_path)
    written = kept = 0
    for entry in entries:
        if entry.is_header:
            continue
        derived_before = DERIVED in entry.comments
        if entry.msgstr and not derived_before:
            kept += 1
            continue
        value = value_for(entry)
        if value and value != entry.msgid:
            entry.msgstr = value
            if not derived_before:
                entry.comments.append(DERIVED)
            written += 1
        elif derived_before:
            entry.msgstr = ""
            entry.comments.remove(DERIVED)
    po.write_po(target_path, entries)
    return written, kept


def _derive_sparse(po, template, target_path: Path, value_for) -> tuple[int, int]:
    """Rewrite a sparse catalog from the template: hand-made entries that differ
    from the source, plus every derived value that changes the text."""
    current = po.read_po(target_path)
    existing = {e.key: e for e in current if not e.is_header}
    out = [e for e in current if e.is_header]
    written = kept = 0
    for entry in template:
        if entry.is_header:
            continue
        old = existing.get(entry.key)
        if old is not None and old.msgstr and DERIVED not in old.comments:
            if old.msgstr != old.msgid:
                out.append(old)
                kept += 1
            continue
        value = value_for(entry)
        if value and value != entry.msgid:
            out.append(po.PoEntry(msgid=entry.msgid, msgctxt=entry.msgctxt, msgstr=value,
                                  comments=[DERIVED]))
            written += 1
    po.write_po(target_path, out)
    return written, kept


def main(argv=None) -> int:
    constants, po = load_runtime_package()
    locale_dir = constants.LOCALE_DIR
    source = {e.key: e.msgstr for e in po.read_po(locale_dir / "sr_RS.po")
              if not e.is_header and e.msgstr and not e.fuzzy}
    written, kept = _derive(po, locale_dir / "sr_RS@latin.po",
                            lambda e: serbian_latin(source[e.key]) if e.key in source else "")
    print(f"sr_RS@latin: {written} transliterated, {kept} hand-made kept")
    template_path = locale_dir / constants.TEMPLATE_NAME
    if not template_path.is_file():
        print("derive_catalogs: no template, run extract_messages.py first", file=sys.stderr)
        return 2
    written, kept = _derive_sparse(po, po.read_po(template_path), locale_dir / "en_GB.po",
                                   lambda e: british(e.msgid))
    print(f"en_GB: {written} respelled, {kept} hand-made kept")
    return 0


if __name__ == "__main__":
    sys.exit(main())
