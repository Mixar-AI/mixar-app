#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Mixar AI
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/open_source/run_phase1_audit.sh [--output-dir DIR]

Runs the Phase 1 open-source readiness audits:
  - secret and sensitive-history scan
  - license and asset inventory

The script never pushes, deletes, rewrites history, or installs tools.
USAGE
}

OUTPUT_DIR="docs/open-source/audit/$(date -u +%Y%m%dT%H%M%SZ)"

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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
mkdir -p "$OUTPUT_DIR"

"$SCRIPT_DIR/phase1_secret_audit.sh" --output-dir "$OUTPUT_DIR/secret-audit"
"$SCRIPT_DIR/phase1_license_asset_inventory.sh" --output-dir "$OUTPUT_DIR/license-asset-audit"

{
  echo "Phase 1 audit completed at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "Repository: $(git rev-parse --show-toplevel)"
  echo "Commit: $(git rev-parse HEAD)"
  echo
  echo "Reports:"
  echo "- $OUTPUT_DIR/secret-audit"
  echo "- $OUTPUT_DIR/license-asset-audit"
} > "$OUTPUT_DIR/summary.txt"

echo "Phase 1 audit reports written to $OUTPUT_DIR"
