#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Apply, reformat, and extend SPDX headers in source files.

Five composable operations:

- Default (no flags): if a file has no SPDX block, insert one using
  ``--copyright`` and ``--license``. Files that already have an SPDX block
  are skipped.
- ``--reformat``: normalize spacing inside an existing SPDX block (separator
  line between the last copyright and the license, single blank line before
  the next non-comment line). All copyright lines and the license id are
  preserved verbatim. Files with no SPDX block are skipped.
- ``--add-copyright TEXT``: ensure ``TEXT`` appears as a
  ``SPDX-FileCopyrightText`` line. If the file has no block, one is created
  with ``--copyright`` and ``TEXT`` stacked. If the block exists and lacks
  ``TEXT``, the line is appended below the existing copyrights. Idempotent.
- ``--migrate-license FROM TO``: in files whose existing SPDX block has
  license id exactly equal to ``FROM``, replace it with ``TO``. Files with
  no SPDX block, or with any other license id, are skipped.
- ``--mixar-policy``: classify each file and apply the correct SPDX:
    * Brand assets (logos, icons, wordmarks per MIXAR_BRAND_ASSETS) →
      ``LicenseRef-Mixar-Brand``.
    * Modified Blender files (counterpart exists under ``--upstream-root``,
      default ``upstream/``) → match upstream's ``SPDX-License-Identifier``
      (or default to ``GPL-2.0-or-later``); ensure Mixar copyright is
      appended below upstream's.
    * Mixar-new files (no upstream counterpart) → ``GPL-3.0-or-later``,
      Mixar copyright appended.
  Composable with ``--reformat`` and ``--add-copyright`` (additional
  copyright lines beyond Mixar's default).

The script never deletes, rewrites, or replaces existing copyright lines.
The license id is rewritten only by ``--migrate-license`` and
``--mixar-policy``, both of which write specific deterministic targets.

Dry-run is the default. Pass ``--write`` to modify files.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


DEFAULT_LICENSE = "GPL-3.0-or-later"
DEFAULT_COPYRIGHT = "2026 Adeveda Enterprises Private Limited"

SPDX_LICENSE_TAG = "SPDX-License-" "Identifier:"
SPDX_COPYRIGHT_TAG = "SPDX-FileCopyright" "Text:"
SPDX_LICENSE_RE = re.compile(re.escape(SPDX_LICENSE_TAG) + r"\s*([A-Za-z0-9.+\-() ]+)")

HASH_EXTS = {
    ".cmake", ".py", ".pyw", ".sh", ".bash", ".ps1",
    ".yml", ".yaml", ".toml", ".txt", ".rst",
}
HTML_EXTS = {".md", ".html", ".htm", ".xml", ".svg", ".plist"}
CSTYLE_EXTS = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".m", ".mm", ".rc"}
BAT_EXTS = {".bat", ".cmd"}

HASH = "hash"
SLASH = "slash"
CBLOCK = "cblock"
HTML = "html"
BAT = "bat"


@dataclass
class SPDXBlock:
    style: str
    start: int
    end: int
    copyrights: list[str]
    license: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="Files to inspect relative to --root")
    parser.add_argument("--paths-from", help="Newline-delimited file of paths relative to --root")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--write", action="store_true", help="Modify files in place")
    parser.add_argument(
        "--infer-from-siblings",
        action="store_true",
        help="Use the most common SPDX license in the nearest containing directory",
    )
    parser.add_argument("--license", default=DEFAULT_LICENSE, help="License id for new headers")
    parser.add_argument("--copyright", default=DEFAULT_COPYRIGHT, help="Copyright text for new headers")
    parser.add_argument(
        "--reformat",
        action="store_true",
        help="Normalize spacing inside existing SPDX blocks (no content change)",
    )
    parser.add_argument(
        "--add-copyright",
        default=None,
        help="Ensure this SPDX-FileCopyrightText line is present (append if missing)",
    )
    parser.add_argument(
        "--migrate-license",
        nargs=2,
        metavar=("FROM", "TO"),
        default=None,
        help=(
            "In files whose existing SPDX-License-Identifier is exactly FROM, "
            "replace it with TO. Files without an SPDX block, or with any "
            "other identifier, are skipped."
        ),
    )
    parser.add_argument(
        "--mixar-policy",
        action="store_true",
        help=(
            "Apply Mixar's per-file licensing policy: brand assets get "
            "LicenseRef-Mixar-Brand; modified Blender files (those with a "
            "counterpart in --upstream-root) keep upstream's license and gain "
            "a Mixar copyright line; Mixar-new files (no upstream counterpart) "
            "get GPL-3.0-or-later. The Mixar copyright (--copyright) is "
            "ensured present on every processed file."
        ),
    )
    parser.add_argument(
        "--upstream-root",
        default="upstream",
        help="Path to upstream Blender submodule root (default: 'upstream')",
    )
    return parser.parse_args()


# Mixar brand assets — must carry LicenseRef-Mixar-Brand. Sourced from
# REUSE.toml's brand annotation block. Update both this list and
# REUSE.toml when adding new brand assets.
MIXAR_BRAND_ASSETS = frozenset({
    "src/release/darwin/Mixar.app/Contents/Resources/Mixar_Legacy_Document_Icon.icns",
    "src/release/darwin/Mixar.app/Contents/Resources/mixar_icon.icns",
    "src/release/datafiles/blender_icons16/icon16_mixar_icon.dat",
    "src/release/datafiles/blender_icons32/icon32_mixar_icon.dat",
    "src/release/datafiles/icons_svg/mixar_icon.svg",
    "src/release/datafiles/mixar_icons.svg",
    "src/release/freedesktop/icons/scalable/apps/mixar.svg",
    "src/release/freedesktop/icons/symbolic/apps/mixar-symbolic.svg",
    "src/release/windows/icons/winmixar.ico",
    "src/release/windows/icons/winmixarfile.ico",
    "src/scripts/mixar/modules/onboarding/assets/mixar_logo.png",
})


def upstream_counterpart(rel_path: str, upstream_root: Path) -> Path | None:
    """Map a src/ path to its upstream/ counterpart if one exists.

    The overlay build copies upstream/ → source/, then src/ overlays on
    top. So a file at src/X corresponds to upstream/X in the submodule.
    Files outside src/ (e.g. top-level configs) have no upstream
    counterpart and are treated as Mixar-new.
    """
    if not rel_path.startswith("src/"):
        return None
    candidate = upstream_root / rel_path[len("src/"):]
    return candidate if candidate.is_file() else None


def read_upstream_license(path: Path) -> str | None:
    """Read SPDX-License-Identifier from an upstream file."""
    try:
        head = path.read_bytes()[:4096]
        if b"\x00" in head:
            return None
        text = head.decode("utf-8", errors="replace")
    except OSError:
        return None
    m = SPDX_LICENSE_RE.search(text)
    return m.group(1).rstrip(" -") if m else None


def mixar_policy_target(rel_path: str, upstream_root: Path,
                       default_copyright: str) -> tuple[str | None, str, bool]:
    """Decide the SPDX target for a file under Mixar's licensing policy.

    Returns (target_license, copyright_to_ensure, is_brand_asset).
      target_license: license id this file should carry, or None to leave
        alone (e.g. unknown upstream).
      copyright_to_ensure: Mixar copyright line to ensure is present.
      is_brand_asset: True if the file is a Mixar brand asset.
    """
    if rel_path in MIXAR_BRAND_ASSETS:
        return "LicenseRef-Mixar-Brand", default_copyright, True
    upstream = upstream_counterpart(rel_path, upstream_root)
    if upstream is not None:
        # Modified Blender file. Match upstream's license; default to
        # GPL-2.0-or-later if upstream has no inline declaration (Blender's
        # umbrella license).
        upstream_lic = read_upstream_license(upstream) or "GPL-2.0-or-later"
        return upstream_lic, default_copyright, False
    # Mixar-new file — should be GPL-3.0-or-later.
    return "GPL-3.0-or-later", default_copyright, False


def read_text(path: Path) -> str | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\0" in raw:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def newline_for(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def canonical_style(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext in CSTYLE_EXTS:
        return CBLOCK
    if ext in HTML_EXTS:
        return HTML
    if ext in BAT_EXTS:
        return BAT
    if ext in HASH_EXTS or path.name in {"Makefile", "GNUmakefile"}:
        return HASH
    return None


def insertion_index(lines: list[str], path: Path) -> int:
    if not lines:
        return 0
    index = 0
    if lines[0].startswith("#!"):
        index = 1
    if path.suffix.lower() in {".py", ".pyw"} and len(lines) > index:
        if re.match(r"^#.*coding[:=]\s*[-\w.]+", lines[index]):
            index += 1
    if path.suffix.lower() in HTML_EXTS and lines[0].lstrip().startswith("<?xml"):
        index = 1
    return index


def _strip_trailing_block_close(value: str) -> str:
    value = value.rstrip("\r\n").rstrip()
    if value.endswith("*/"):
        value = value[:-2].rstrip()
    if value.endswith("-->"):
        value = value[:-3].rstrip()
    return value


def _copyright_in(line: str) -> str | None:
    idx = line.find(SPDX_COPYRIGHT_TAG)
    if idx < 0:
        return None
    rest = line[idx + len(SPDX_COPYRIGHT_TAG):].lstrip()
    rest = _strip_trailing_block_close(rest)
    return rest or None


def _license_in(line: str) -> str | None:
    m = SPDX_LICENSE_RE.search(line)
    if not m:
        return None
    return m.group(1).rstrip(" -")


def find_spdx_block(lines: list[str], start: int) -> SPDXBlock | None:
    """Locate the SPDX block at or shortly after ``start``. ``None`` if absent."""
    i = start
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    if i >= len(lines):
        return None

    stripped = lines[i].lstrip()
    if stripped.startswith("/*"):
        return _parse_cblock(lines, i)
    if stripped.startswith("//"):
        return _parse_line_run(lines, i, "//", SLASH)
    if stripped.startswith("<!--"):
        return _parse_html(lines, i)
    if stripped.startswith("REM"):
        return _parse_line_run(lines, i, "REM", BAT)
    if stripped.startswith("#"):
        return _parse_line_run(lines, i, "#", HASH)
    return None


def _parse_line_run(lines: list[str], start: int, marker: str, style: str) -> SPDXBlock | None:
    """Parse a contiguous block of single-line comments using ``marker``."""
    copyrights: list[str] = []
    license_id: str | None = None
    first_spdx = -1
    last_spdx = -1

    i = start
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped == "" or not stripped.startswith(marker):
            break
        cop = _copyright_in(lines[i])
        lic = _license_in(lines[i])
        if cop:
            copyrights.append(cop)
            if first_spdx < 0:
                first_spdx = i
            last_spdx = i
        elif lic:
            license_id = lic
            if first_spdx < 0:
                first_spdx = i
            last_spdx = i
        elif stripped == marker:
            if first_spdx < 0:
                break
        else:
            if first_spdx >= 0:
                break
            i += 1
            continue
        i += 1

    if first_spdx < 0:
        return None
    return SPDXBlock(style=style, start=first_spdx, end=last_spdx + 1,
                     copyrights=copyrights, license=license_id)


def _parse_cblock(lines: list[str], start: int) -> SPDXBlock | None:
    end = start
    while end < len(lines):
        if "*/" in lines[end]:
            break
        end += 1
    if end >= len(lines):
        return None

    copyrights: list[str] = []
    license_id: str | None = None
    for k in range(start, end + 1):
        cop = _copyright_in(lines[k])
        if cop:
            copyrights.append(cop)
        lic = _license_in(lines[k])
        if lic:
            license_id = lic

    if not copyrights and not license_id:
        return None
    return SPDXBlock(style=CBLOCK, start=start, end=end + 1,
                     copyrights=copyrights, license=license_id)


def _parse_html(lines: list[str], start: int) -> SPDXBlock | None:
    copyrights: list[str] = []
    license_id: str | None = None
    first_spdx = -1
    last_spdx = -1
    i = start
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped == "" or not stripped.startswith("<!--"):
            break
        cop = _copyright_in(lines[i])
        lic = _license_in(lines[i])
        if cop:
            copyrights.append(cop)
            if first_spdx < 0:
                first_spdx = i
            last_spdx = i
        elif lic:
            license_id = lic
            if first_spdx < 0:
                first_spdx = i
            last_spdx = i
        elif first_spdx >= 0:
            break
        i += 1
    if first_spdx < 0:
        return None
    return SPDXBlock(style=HTML, start=first_spdx, end=last_spdx + 1,
                     copyrights=copyrights, license=license_id)


def emit_block(block: SPDXBlock, newline: str) -> list[str]:
    if block.style == HASH:
        return _emit_with_marker(block, "#", newline)
    if block.style == SLASH:
        return _emit_with_marker(block, "//", newline)
    if block.style == BAT:
        return _emit_with_marker(block, "REM", newline)
    if block.style == HTML:
        return _emit_html(block, newline)
    if block.style == CBLOCK:
        return _emit_cblock(block, newline)
    raise ValueError(f"unknown style: {block.style}")


def _emit_with_marker(block: SPDXBlock, marker: str, newline: str) -> list[str]:
    out: list[str] = []
    for cop in block.copyrights:
        out.append(f"{marker} {SPDX_COPYRIGHT_TAG} {cop}{newline}")
    if block.license:
        out.append(f"{marker}{newline}")
        out.append(f"{marker} {SPDX_LICENSE_TAG} {block.license}{newline}")
    return out


def _emit_html(block: SPDXBlock, newline: str) -> list[str]:
    out = [f"<!-- {SPDX_COPYRIGHT_TAG} {cop} -->{newline}" for cop in block.copyrights]
    if block.license:
        out.append(f"<!-- {SPDX_LICENSE_TAG} {block.license} -->{newline}")
    return out


def _emit_cblock(block: SPDXBlock, newline: str) -> list[str]:
    if not block.copyrights and not block.license:
        return []
    out: list[str] = []
    if block.copyrights:
        out.append(f"/* {SPDX_COPYRIGHT_TAG} {block.copyrights[0]}{newline}")
        for cop in block.copyrights[1:]:
            out.append(f" * {SPDX_COPYRIGHT_TAG} {cop}{newline}")
        if block.license:
            out.append(f" *{newline}")
            out.append(f" * {SPDX_LICENSE_TAG} {block.license} */{newline}")
        else:
            last = out.pop().rstrip("\r\n")
            out.append(f"{last} */{newline}")
    else:
        out.append(f"/* {SPDX_LICENSE_TAG} {block.license} */{newline}")
    return out


def infer_license(root: Path, path: Path, fallback: str) -> str:
    directory = path.parent
    while True:
        counts: Counter[str] = Counter()
        for candidate in directory.iterdir():
            if not candidate.is_file() or candidate == path:
                continue
            text = read_text(candidate)
            if text is None:
                continue
            counts.update(SPDX_LICENSE_RE.findall(text))
        if counts:
            return counts.most_common(1)[0][0].rstrip(" -")
        if directory == root:
            return fallback
        directory = directory.parent


def process_file(root: Path, rel_path: str, args: argparse.Namespace) -> tuple[str, str]:
    path = root / rel_path
    text = read_text(path)
    if text is None:
        return rel_path, "skip: unreadable-or-binary"

    style = canonical_style(path)
    if style is None:
        return rel_path, "skip: unsupported-comment-style"

    newline = newline_for(text)
    lines = text.splitlines(keepends=True)
    insert_at = insertion_index(lines, path)
    block = find_spdx_block(lines, insert_at)

    migrate_from, migrate_to = (args.migrate_license or (None, None))

    # --mixar-policy computes a per-file (target_license, copyright_to_add)
    # from the file's classification: brand asset / modified-Blender / Mixar-new.
    # When set, it overrides --license, --migrate-license, and --add-copyright
    # for this file with the policy's choices.
    policy_target_license: str | None = None
    policy_copyright: str | None = None
    if args.mixar_policy:
        upstream_root = Path(args.upstream_root)
        policy_target_license, policy_copyright, _is_brand = mixar_policy_target(
            rel_path, upstream_root, args.copyright
        )

    if block is None:
        # No existing SPDX block. Default-add behavior; for --mixar-policy
        # this uses the policy's target license and ensures the policy
        # copyright is present.
        if args.migrate_license and not args.add_copyright and not args.reformat and not args.mixar_policy:
            return rel_path, "skip: no-existing-block"
        if args.reformat and not args.add_copyright and not args.mixar_policy:
            return rel_path, "skip: no-existing-block"
        if args.mixar_policy:
            license_id = policy_target_license or args.license
        else:
            license_id = (
                infer_license(root, path, args.license)
                if args.infer_from_siblings
                else args.license
            )
        copyrights = [policy_copyright or args.copyright]
        if args.add_copyright and args.add_copyright != copyrights[0]:
            copyrights.append(args.add_copyright)
        new_block = SPDXBlock(style=style, start=insert_at, end=insert_at,
                              copyrights=copyrights, license=license_id)
        block_lines = emit_block(new_block, newline)
        trailing = [newline] if insert_at < len(lines) and lines[insert_at].strip() != "" else []
        new_lines = lines[:insert_at] + block_lines + trailing + lines[insert_at:]
    else:
        if not args.reformat and not args.add_copyright and not args.migrate_license and not args.mixar_policy:
            return rel_path, "skip: already-has-spdx"
        copyrights = list(block.copyrights)
        added = False
        if args.add_copyright and args.add_copyright not in copyrights:
            copyrights.append(args.add_copyright)
            added = True
        if args.mixar_policy and policy_copyright and policy_copyright not in copyrights:
            copyrights.append(policy_copyright)
            added = True
        new_license = block.license
        migrated = False
        if migrate_from and block.license == migrate_from:
            new_license = migrate_to
            migrated = True
        if args.mixar_policy and policy_target_license and block.license != policy_target_license:
            new_license = policy_target_license
            migrated = True
        if not args.reformat and not added and not migrated:
            return rel_path, "skip: already-has-spdx"
        new_block = SPDXBlock(style=block.style, start=block.start, end=block.end,
                              copyrights=copyrights, license=new_license)
        block_lines = emit_block(new_block, newline)
        after = lines[block.end:]
        trailing = [newline] if after and after[0].strip() != "" else []
        new_lines = lines[:block.start] + block_lines + trailing + after

    new_text = "".join(new_lines)
    if new_text == text:
        return rel_path, "skip: already-canonical"
    if args.write:
        # write_bytes preserves the exact newline bytes we constructed in
        # `new_text`. Path.write_text(newline="") would do the same on
        # Python 3.10+, but the `newline=` kwarg is 3.10+ only; using
        # write_bytes keeps the script 3.9-compatible without behaviour change.
        path.write_bytes(new_text.encode("utf-8"))
        return rel_path, "updated"
    return rel_path, "would update"


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    paths = list(args.paths)
    if args.paths_from:
        paths.extend(line for line in Path(args.paths_from).read_text().splitlines() if line.strip())
    if not paths:
        print("No paths provided", file=sys.stderr)
        return 2

    changed = 0
    skipped = 0
    for rel_path in paths:
        rel_path = os.fspath(Path(rel_path))
        _, status = process_file(root, rel_path, args)
        print(f"{status}: {rel_path}")
        if status in {"updated", "would update"}:
            changed += 1
        else:
            skipped += 1

    if not args.write and changed:
        print(f"{changed} file(s) would be updated; rerun with --write to modify.")
        return 1
    print(f"{changed} changed, {skipped} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
