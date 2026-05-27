#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Mixar AI
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/open_source/phase1_license_asset_inventory.sh [--output-dir DIR]

Builds a publication-oriented inventory of Git-visible assets, SPDX notices,
license files, and source files missing SPDX identifiers.
USAGE
}

OUTPUT_DIR="docs/open-source/audit/license-asset-audit"
SPDX_LICENSE_TAG='SPDX-License-''Identifier:'

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-dir)
      OUTPUT_DIR="${2:?--output-dir requires a value}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

mkdir -p "$OUTPUT_DIR"

GIT_VISIBLE_NUL="$OUTPUT_DIR/git-visible-paths.nul"
TRACKED_NUL="$OUTPUT_DIR/git-visible-files.nul"
git ls-files -z --cached --others --exclude-standard > "$GIT_VISIBLE_NUL"
: > "$TRACKED_NUL"
while IFS= read -r -d '' path; do
  if [[ -f "$path" ]]; then
    printf '%s\0' "$path" >> "$TRACKED_NUL"
  fi
done < "$GIT_VISIBLE_NUL"
tr '\0' '\n' < "$TRACKED_NUL" > "$OUTPUT_DIR/tracked-files.txt"

ASSET_REGEX='\.(blend|png|jpg|jpeg|gif|webp|svg|ico|icns|bmp|pdf|dat|xml|theme|msi|dmg|zip|tar|zst|7z|rar|hdr|exr|ttf|otf|woff|woff2)$'
SOURCE_REGEX='\.(py|pyw|c|cc|cpp|cxx|h|hh|hpp|hxx|m|mm|cmake|sh|bash|bat|ps1|rc|yml|yaml|toml|json|xml|md|rst|txt)$'

rg -n -i --color never -e "$ASSET_REGEX" "$OUTPUT_DIR/tracked-files.txt" \
  | sed -E 's/^[0-9]+://' \
  > "$OUTPUT_DIR/tracked-assets.txt" || true

rg -n -i --color never -e '(^|/)(LICENSE|COPYING|NOTICE|THIRD_PARTY|README\.blender)(\.|$|/)' "$OUTPUT_DIR/tracked-files.txt" \
  | sed -E 's/^[0-9]+://' \
  > "$OUTPUT_DIR/license-notice-files.txt" || true

if [[ -s "$TRACKED_NUL" ]]; then
  : > "$OUTPUT_DIR/spdx-lines.txt"
  while IFS= read -r -d '' path; do
    rg -n -I --color never -S -e "$SPDX_LICENSE_TAG" "$path" \
      | sed "s|^|$path:|" \
      >> "$OUTPUT_DIR/spdx-lines.txt" || true
  done < "$TRACKED_NUL"
else
  : > "$OUTPUT_DIR/spdx-lines.txt"
fi

sed -E "s/.*${SPDX_LICENSE_TAG}[[:space:]]*//; s/[[:space:]]*(-->|\\*\\/|#|;)[[:space:]]*$//; s/[[:space:]]+$//" "$OUTPUT_DIR/spdx-lines.txt" \
  | grep -E '^[A-Za-z0-9.+() -]+$' \
  | sort \
  | uniq -c \
  | sed -E 's/^ *//' \
  > "$OUTPUT_DIR/spdx-summary.txt" || true

rg -n -i --color never -e "$SOURCE_REGEX" "$OUTPUT_DIR/tracked-files.txt" \
  | sed -E 's/^[0-9]+://' \
  | grep -v '^LICENSES/' \
  > "$OUTPUT_DIR/source-like-files.txt" || true

cut -d: -f1 "$OUTPUT_DIR/spdx-lines.txt" | sort -u > "$OUTPUT_DIR/files-with-spdx.txt"
comm -23 \
  <(sort -u "$OUTPUT_DIR/source-like-files.txt") \
  <(sort -u "$OUTPUT_DIR/files-with-spdx.txt") \
  > "$OUTPUT_DIR/source-like-files-without-spdx.txt" || true

{
  echo "Optional tool availability"
  echo
  if command -v reuse >/dev/null 2>&1; then
    echo "reuse: available"
    reuse --no-multiprocessing lint > "$OUTPUT_DIR/reuse-lint.txt" 2>&1 || true
  else
    echo "reuse: not installed"
  fi
  if command -v syft >/dev/null 2>&1; then
    echo "syft: available"
    syft scan dir:. \
      --exclude './.git/**' \
      --exclude './.worktrees/**' \
      --exclude './build/**' \
      --exclude './dist/**' \
      --exclude './source/**' \
      --exclude './upstream/lib/**' \
      --exclude './docs/open-source/audit/**' \
      --output "syft-json=$OUTPUT_DIR/syft-sbom.json" \
      --output "syft-table=$OUTPUT_DIR/syft-packages.txt" \
      > "$OUTPUT_DIR/syft-stdout.txt" 2> "$OUTPUT_DIR/syft-stderr.txt" || true
  else
    echo "syft: not installed"
  fi
} > "$OUTPUT_DIR/optional-tools.txt"

{
  echo "License and asset inventory summary"
  echo
  echo "Git-visible files inventoried: $(wc -l < "$OUTPUT_DIR/tracked-files.txt" | tr -d ' ')"
  echo "Git-visible asset files: $(wc -l < "$OUTPUT_DIR/tracked-assets.txt" | tr -d ' ')"
  echo "License/notice files: $(wc -l < "$OUTPUT_DIR/license-notice-files.txt" | tr -d ' ')"
  echo "SPDX lines: $(wc -l < "$OUTPUT_DIR/spdx-lines.txt" | tr -d ' ')"
  echo "Source-like files without inline SPDX: $(wc -l < "$OUTPUT_DIR/source-like-files-without-spdx.txt" | tr -d ' ')"
  echo
  echo "Review required:"
  echo "- tracked-assets.txt"
  echo "- license-notice-files.txt"
  echo "- spdx-summary.txt"
  echo "- source-like-files-without-spdx.txt"
  echo "- optional-tools.txt"
  echo "- reuse-lint.txt if generated"
  echo "- syft-sbom.json and syft-packages.txt if generated"
} > "$OUTPUT_DIR/summary.txt"

echo "License and asset inventory reports written to $OUTPUT_DIR"
