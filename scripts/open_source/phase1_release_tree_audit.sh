#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Mixar AI
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/open_source/phase1_release_tree_audit.sh --ref REF [--output-dir DIR]

Exports REF into a clean temporary tree and scans only that exported tree. This
is the release gate for public source drops because it avoids generated local
trees, worktrees, build outputs, and ignored artifacts.
USAGE
}

REF=""
OUTPUT_DIR="docs/open-source/audit/release-tree-audit"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ref)
      REF="${2:?--ref requires a value}"
      shift 2
      ;;
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

if [[ -z "$REF" ]]; then
  echo "--ref is required" >&2
  usage >&2
  exit 2
fi

mkdir -p "$OUTPUT_DIR"

EXPORT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/mixar-release-tree-audit.XXXXXX")"
trap 'rm -rf "$EXPORT_DIR"' EXIT

git archive "$REF" | tar -x -C "$EXPORT_DIR"

{
  echo "Release tree audit"
  echo
  echo "Ref: $REF"
  echo "Commit: $(git rev-parse "$REF^{commit}")"
  echo "Exported file count: $(find "$EXPORT_DIR" -type f | wc -l | tr -d ' ')"
} > "$OUTPUT_DIR/summary.txt"

if command -v gitleaks >/dev/null 2>&1; then
  gitleaks dir "$EXPORT_DIR" --redact --report-format json \
    --report-path "$OUTPUT_DIR/gitleaks-release-tree-report.json" \
    > "$OUTPUT_DIR/gitleaks-release-tree-stdout.txt" \
    2> "$OUTPUT_DIR/gitleaks-release-tree-stderr.txt" || true
else
  echo "gitleaks: not installed" > "$OUTPUT_DIR/gitleaks-release-tree-stdout.txt"
fi

if command -v trufflehog >/dev/null 2>&1; then
  trufflehog filesystem "$EXPORT_DIR" --results=verified,unknown --json \
    > "$OUTPUT_DIR/trufflehog-release-tree-report.jsonl" \
    2> "$OUTPUT_DIR/trufflehog-release-tree-stderr.txt" || true
else
  echo "trufflehog: not installed" > "$OUTPUT_DIR/trufflehog-release-tree-stderr.txt"
fi

if command -v syft >/dev/null 2>&1; then
  syft scan "dir:$EXPORT_DIR" \
    --output "syft-json=$OUTPUT_DIR/syft-release-tree-sbom.json" \
    --output "syft-table=$OUTPUT_DIR/syft-release-tree-packages.txt" \
    > "$OUTPUT_DIR/syft-release-tree-stdout.txt" \
    2> "$OUTPUT_DIR/syft-release-tree-stderr.txt" || true
fi

{
  echo
  echo "Tool summaries:"
  if [[ -f "$OUTPUT_DIR/gitleaks-release-tree-report.json" ]]; then
    echo "gitleaks findings: $(jq 'length' "$OUTPUT_DIR/gitleaks-release-tree-report.json" 2>/dev/null || echo unknown)"
  fi
  if [[ -f "$OUTPUT_DIR/trufflehog-release-tree-report.jsonl" ]]; then
    echo "trufflehog findings: $(wc -l < "$OUTPUT_DIR/trufflehog-release-tree-report.jsonl" | tr -d ' ')"
  fi
  if [[ -f "$OUTPUT_DIR/syft-release-tree-sbom.json" ]]; then
    echo "syft artifacts: $(jq '.artifacts | length' "$OUTPUT_DIR/syft-release-tree-sbom.json" 2>/dev/null || echo unknown)"
  fi
} >> "$OUTPUT_DIR/summary.txt"

echo "Release tree audit reports written to $OUTPUT_DIR"
