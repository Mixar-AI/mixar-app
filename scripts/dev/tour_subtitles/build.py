#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Build English-timed fallback tracks; --check detects stale/missing output.

en.json is the cue schedule for the bundled English edit. Each UTF-8 .txt
contains one translated cue per line, in logical reading order. These are
machine-translated drafts for native-speaker review. Never translate the
timestamps or align these tracks to the length of a dubbed recording.

The original nine dub-derived tracks retain their own English-aligned cues.
Arabic's logical source is kept here so its BLF shaping is reproducible too.
"""

import argparse
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / "src/scripts/mixar/modules/onboarding/assets/tour/subtitles"
sys.path.insert(0, str(ROOT / "scripts/i18n"))
from derive_catalogs import serbian_latin
from rtl import log2vis


def stamp(ms):
    seconds, millis = divmod(ms, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"


def tracks():
    schedule = json.loads((HERE / "en.json").read_text(encoding="utf-8"))
    texts = {"en": [row[2] for row in schedule]}
    texts.update({p.stem: p.read_text(encoding="utf-8").splitlines()
                  for p in sorted(HERE.glob("*.txt"))})
    texts["sr_RS@latin"] = [serbian_latin(s) for s in texts["sr_RS"]]
    for code, lines in texts.items():
        if len(lines) != len(schedule) or not all(line.strip() for line in lines):
            raise ValueError(f"{code}: expected {len(schedule)} nonempty cues")
        blocks = []
        for i, ((start, end, _source), text) in enumerate(zip(schedule, lines), 1):
            if code in {"fa_IR", "he_IL", "ur"}:
                text = log2vis(text)
            blocks.append(f"{i}\n{stamp(start)} --> {stamp(end)}\n{text}\n")
        yield code, "\n".join(blocks)
    # Keep the original Arabic cue timings, shape only the display text.
    blocks = []
    for block in re.split(r"\n\s*\n", (HERE / "ar.srt").read_text().strip()):
        index, timing, text = block.split("\n", 2)
        blocks.append(f"{index}\n{timing}\n{log2vis(text)}\n")
    yield "ar", "\n".join(blocks)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale = []
    count = 0
    for code, text in tracks():
        path = OUT / f"{code}.srt"
        count += 1
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                stale.append(code)
        else:
            path.write_text(text, encoding="utf-8")
    if stale:
        parser.exit(1, f"Stale subtitles: {', '.join(stale)}\n")
    print(f"{'Checked' if args.check else 'Built'} {count} subtitle tracks")


if __name__ == "__main__":
    main()
