#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Create a CSV checklist for asset provenance review."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


DEFAULT_INPUT = "docs/open-source/audit/20260518T-license-cleanup-final-3/tracked-assets.txt"
DEFAULT_OUTPUT = "docs/open-source/asset-provenance-review.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=DEFAULT_INPUT, help="Asset path list, one path per line")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="CSV review file to create")
    return parser.parse_args()


def asset_group(path: str) -> str:
    if path.startswith("src/release/"):
        return "release-resource"
    if "procedural_materials" in path:
        return "procedural-material"
    if path.endswith(".blend"):
        return "blend-file"
    if "onboarding/assets" in path:
        return "brand-asset"
    return "asset"


def initial_license(path: str) -> str:
    if "mixar_logo" in path or "mixar_icon" in path or "winmixar" in path:
        return "GPL-3.0-or-later"
    return "GPL-2.0-or-later"


def initial_status(path: str) -> str:
    if "mixar_logo" in path or "mixar_icon" in path or "winmixar" in path:
        return "Mixar-owned"
    return "Open-source"


def initial_owner(path: str) -> str:
    if initial_status(path) == "Mixar-owned":
        return "Adeveda Enterprises Private Limited"
    return "Open-source contributors"


def initial_notes(path: str) -> str:
    if initial_status(path) == "Mixar-owned":
        return "trademark-reserved for Mixar brand marks"
    return ""


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)

    assets = [line.strip() for line in input_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "path",
                "asset_group",
                "provenance_status",
                "copyright_owner",
                "spdx_license",
                "evidence_or_source",
                "action",
                "notes",
            ]
        )
        for path in assets:
            writer.writerow(
                [
                    path,
                    asset_group(path),
                    initial_status(path),
                    initial_owner(path),
                    initial_license(path),
                    "Open-source source tree",
                    "keep",
                    initial_notes(path),
                ]
            )

    print(f"Wrote {len(assets)} asset review rows to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
