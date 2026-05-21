#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

set -euo pipefail

# Upstream Overlay Conflict Detector
# Detects when upstream Blender changes files that Mixar also overlays.
#
# Usage:
#   ./check_overlay_conflicts.sh --generate   Generate/update the manifest
#   ./check_overlay_conflicts.sh --check      Check for upstream changes (default)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/settings.sh"

MANIFEST_FILE="$ROOT_DIR/.overlay_manifest"

# Cross-platform SHA-256: macOS has shasum, Linux has sha256sum
sha256() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    else
        shasum -a 256 "$1" | awk '{print $1}'
    fi
}

# Find all overlay files in src/ that correspond to upstream files
find_overlaid_upstream_files() {
    cd "$SRC_DIR"
    find . -type f \
        -not -name '.DS_Store' \
        -not -path '*/__pycache__/*' \
        -not -path '*/.git/*' \
    | sort
}

# Generate a manifest of upstream file checksums for all overlaid files
generate_manifest() {
    echo "Generating overlay conflict manifest..."

    local overlay_files
    overlay_files=$(find_overlaid_upstream_files)
    local total=0
    local tracked=0

    > "$MANIFEST_FILE"

    while IFS= read -r rel_path; do
        total=$((total + 1))
        local upstream_file="$UPSTREAM_DIR/$rel_path"
        if [ -f "$upstream_file" ]; then
            local checksum
            checksum=$(sha256 "$upstream_file")
            echo "$checksum  $rel_path" >> "$MANIFEST_FILE"
            tracked=$((tracked + 1))
        fi
    done <<< "$overlay_files"

    echo "Manifest written: $tracked overlaid upstream files tracked (out of $total overlay files)"
    echo "Location: $MANIFEST_FILE"
}

# Check current upstream against the stored manifest
check_conflicts() {
    if [ ! -f "$MANIFEST_FILE" ]; then
        echo "No overlay manifest found. Run with --generate to create one."
        return 0
    fi

    local conflicts=0
    local removed=0
    local checked=0

    while IFS= read -r line; do
        local old_checksum="${line%%  *}"
        local rel_path="${line#*  }"
        local upstream_file="$UPSTREAM_DIR/$rel_path"

        checked=$((checked + 1))

        if [ -f "$upstream_file" ]; then
            local new_checksum
            new_checksum=$(sha256 "$upstream_file")
            if [ "$old_checksum" != "$new_checksum" ]; then
                echo "  CONFLICT: $rel_path"
                conflicts=$((conflicts + 1))
            fi
        else
            echo "  REMOVED:  $rel_path (no longer in upstream)"
            removed=$((removed + 1))
        fi
    done < "$MANIFEST_FILE"

    echo "Checked $checked files."

    if [ "$conflicts" -gt 0 ] || [ "$removed" -gt 0 ]; then
        echo ""
        [ "$conflicts" -gt 0 ] && echo "WARNING: $conflicts file(s) changed in upstream since last manifest."
        [ "$removed" -gt 0 ] && echo "WARNING: $removed file(s) removed from upstream since last manifest."
        echo "Review these files and update overlays as needed."
        echo "Then run: $0 --generate"
        return 1
    fi

    echo "No upstream conflicts detected."
    return 0
}

case "${1:---check}" in
    --generate) generate_manifest ;;
    --check)    check_conflicts ;;
    -h|--help)
        echo "Usage: $0 [--generate|--check]"
        echo ""
        echo "  --generate  Record current upstream checksums for all overlaid files"
        echo "  --check     Compare upstream against manifest to detect changes (default)"
        ;;
    *)
        echo "Unknown option: $1"
        echo "Usage: $0 [--generate|--check]"
        exit 1
        ;;
esac
