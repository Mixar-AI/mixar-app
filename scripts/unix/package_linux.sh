#!/bin/bash
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

set -euo pipefail

# =============================================================================
# Mixar Linux Packaging Script
# Creates a portable .tar.xz archive for distribution.
#
# The output is a self-contained directory that users extract and run directly,
# matching Blender's official Linux distribution format.
#
# Usage:
#   ./package_linux.sh [options]
#
# Options:
#   --env ENV              Override environment (default: from settings/env)
#   --name NAME            Override output archive name (without extension)
#   --skip-freedesktop     Omit .desktop file, icons, and AppStream metadata
#   --no-strip             Do not strip debug symbols from binaries
#   --output-dir DIR       Override output directory (default: ./dist)
#   -h, --help             Show this help message
#
# Examples:
#   ./package_linux.sh                        # package current env
#   ./package_linux.sh --env Prod             # override environment
#   ./package_linux.sh --env Dev --name X     # override env and name
#   ./package_linux.sh --no-strip             # keep debug symbols
# =============================================================================

# ── Resolve script and project paths ─────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/settings.sh"

# ── Parse arguments ──────────────────────────────────────────────────────────
SKIP_FREEDESKTOP=false
DO_STRIP=true
PACKAGE_NAME_OVERRIDE=""

usage() {
    sed -n '/^# Usage:/,/^# =====/p' "$0" | sed 's/^# //' | sed 's/^#//'
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --env)              MIXAR_ENV="$2"; shift 2 ;;
        --name)             PACKAGE_NAME_OVERRIDE="$2"; shift 2 ;;
        --output-dir)       OUTPUT_DIR="$2"; shift 2 ;;
        --skip-freedesktop) SKIP_FREEDESKTOP=true; shift ;;
        --no-strip)         DO_STRIP=false; shift ;;
        -h|--help)          usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

# ── Resolve paths ────────────────────────────────────────────────────────────
BUILD_ENV_DIR="${BUILD_DIR}/${MIXAR_ENV}"
OUTPUT_DIR="${OUTPUT_DIR:-${ROOT_DIR}/dist}"
ARCH="$(uname -m)"
VERSION="${MIXAR_VERSION}"

FREEDESKTOP_DIR="$SOURCE_DIR/release/freedesktop"

# Build archive name: Mixar-{version}-linux-{arch} (omit env for Prod)
if [[ -z "$PACKAGE_NAME_OVERRIDE" ]]; then
    if [[ "$MIXAR_ENV" == "Prod" ]]; then
        PACKAGE_NAME_OVERRIDE="Mixar-${VERSION}-linux-${ARCH}"
    else
        PACKAGE_NAME_OVERRIDE="Mixar-${VERSION}-${MIXAR_ENV}-linux-${ARCH}"
    fi
fi

ARCHIVE_NAME="${PACKAGE_NAME_OVERRIDE}.tar.xz"

# ── Helper ───────────────────────────────────────────────────────────────────
step() {
    echo ""
    echo "============================================================"
    echo "  $1"
    echo "============================================================"
}

echo "============================================================"
echo "  Mixar Linux Packaging Script"
echo "============================================================"
echo "Environment : $MIXAR_ENV"
echo "Build dir   : $BUILD_ENV_DIR"
echo "Output dir  : $OUTPUT_DIR"
echo "Archive     : $ARCHIVE_NAME"
echo "Version     : $VERSION"
echo "Arch        : $ARCH"
echo "Strip       : $DO_STRIP"

# ── [1/7] Verify build exists ───────────────────────────────────────────────
step "[1/7] Verifying build artifacts"

MIXAR_BIN="$BUILD_ENV_DIR/bin/mixar"
if [[ ! -x "$MIXAR_BIN" ]]; then
    echo "Error: Build not found at $MIXAR_BIN"
    echo "  Run 'make build' first before packaging."
    exit 1
fi
echo "Build artifacts found: $MIXAR_BIN"

# ── [2/7] Verify Python packages ────────────────────────────────────────────
step "[2/7] Verifying Python packages"

PY_BASE="$BUILD_ENV_DIR/bin"
SITE_PACKAGES="$PY_BASE/$BLENDER_VERSION/python/lib/python${PYTHON_VERSION}/site-packages"
REQUIREMENTS_FILE="$(dirname "$SCRIPT_DIR")/python_requirements.txt"

# Find the embedded Python binary
PYTHON_BIN=""
for candidate in \
    "$PY_BASE/$BLENDER_VERSION/python/bin/python${PYTHON_VERSION}" \
    "$PY_BASE/$BLENDER_VERSION/python/bin/python3" \
    "$PY_BASE/$BLENDER_VERSION/python/bin/python"; do
    if [[ -x "$candidate" ]]; then
        PYTHON_BIN="$candidate"
        break
    fi
done

if [[ -z "$PYTHON_BIN" ]]; then
    echo "Error: Python binary not found under $PY_BASE/$BLENDER_VERSION/python/bin"
    echo "  Cannot verify required packages. Aborting."
    exit 1
fi

if [[ ! -f "$REQUIREMENTS_FILE" ]]; then
    echo "Error: Requirements file not found at: $REQUIREMENTS_FILE"
    exit 1
fi

echo "Found Python binary: $PYTHON_BIN"
mkdir -p "$SITE_PACKAGES"

echo "Installing/verifying Python packages..."
if ! "$PYTHON_BIN" -m pip install --no-user --target "$SITE_PACKAGES" -r "$REQUIREMENTS_FILE"; then
    echo "Error: Failed to install required Python packages. Aborting."
    exit 1
fi
echo "Python packages verified."

# ── [3/7] Generate runtime config ───────────────────────────────────────────
step "[3/7] Generating runtime configuration"

CONFIG_DIR="$BUILD_ENV_DIR/bin/$BLENDER_VERSION/config"
mkdir -p "$CONFIG_DIR"

python3 "$ROOT_DIR/scripts/generate_config.py" --output "$CONFIG_DIR/mixar.json"
echo "Runtime config generated."

# ── [4/7] Prepare staging directory ─────────────────────────────────────────
step "[4/7] Preparing staging directory"

WORK_DIR="$(mktemp -d)"
STAGING_DIR="$WORK_DIR/$PACKAGE_NAME_OVERRIDE"

cleanup() {
    echo "Cleaning up staging directory..."
    rm -rf "$WORK_DIR"
}
trap cleanup EXIT

echo "Staging to: $STAGING_DIR"

# Copy the entire build output (portable install layout)
cp -a "$BUILD_ENV_DIR/bin/." "$STAGING_DIR/"

echo "Build output staged."

# ── [5/7] Include FreeDesktop files ─────────────────────────────────────────
if [[ "$SKIP_FREEDESKTOP" == true ]]; then
    step "[5/7] Skipping FreeDesktop files (--skip-freedesktop)"
else
    step "[5/7] Including FreeDesktop integration files"

    # Desktop entry
    if [[ -f "$FREEDESKTOP_DIR/mixar.desktop" ]]; then
        cp "$FREEDESKTOP_DIR/mixar.desktop" "$STAGING_DIR/"
        echo "  Added: mixar.desktop"
    else
        echo "  Warning: mixar.desktop not found at $FREEDESKTOP_DIR/"
    fi

    # AppStream metadata
    if [[ -f "$FREEDESKTOP_DIR/org.mixar.Mixar.metainfo.xml" ]]; then
        cp "$FREEDESKTOP_DIR/org.mixar.Mixar.metainfo.xml" "$STAGING_DIR/"
        echo "  Added: org.mixar.Mixar.metainfo.xml"
    fi

    # Icons (preserve directory structure for easy system install)
    ICONS_SRC="$FREEDESKTOP_DIR/icons"
    if [[ -d "$ICONS_SRC" ]]; then
        mkdir -p "$STAGING_DIR/icons/scalable/apps"
        mkdir -p "$STAGING_DIR/icons/symbolic/apps"

        if [[ -f "$ICONS_SRC/scalable/apps/mixar.svg" ]]; then
            cp "$ICONS_SRC/scalable/apps/mixar.svg" "$STAGING_DIR/icons/scalable/apps/"
            echo "  Added: icons/scalable/apps/mixar.svg"
        fi
        if [[ -f "$ICONS_SRC/symbolic/apps/mixar-symbolic.svg" ]]; then
            cp "$ICONS_SRC/symbolic/apps/mixar-symbolic.svg" "$STAGING_DIR/icons/symbolic/apps/"
            echo "  Added: icons/symbolic/apps/mixar-symbolic.svg"
        fi
    else
        echo "  Warning: icons directory not found at $ICONS_SRC"
    fi
fi

# ── [6/7] Strip debug symbols ───────────────────────────────────────────────
if [[ "$DO_STRIP" == true ]]; then
    step "[6/7] Stripping debug symbols from binaries"

    STRIP_COUNT=0
    while IFS= read -r -d '' f; do
        # Only strip ELF binaries and shared libraries
        if file --brief "$f" | grep -qE "ELF.*executable|ELF.*shared object"; then
            strip --strip-debug "$f" 2>/dev/null && STRIP_COUNT=$((STRIP_COUNT + 1)) || true
        fi
    done < <(find "$STAGING_DIR" -type f -print0)

    echo "Stripped debug symbols from $STRIP_COUNT files."
else
    step "[6/7] Skipping symbol stripping (--no-strip)"
fi

# ── [7/7] Create archive ────────────────────────────────────────────────────
step "[7/7] Creating archive: $ARCHIVE_NAME"

mkdir -p "$OUTPUT_DIR"
ARCHIVE_PATH="$OUTPUT_DIR/$ARCHIVE_NAME"

# Remove existing archive if present
rm -f "$ARCHIVE_PATH"

# Create .tar.xz with maximum compression (matches build_archive.py approach)
export XZ_OPT="-9"
tar -cf "$ARCHIVE_PATH" \
    --owner=0 --group=0 \
    --use-compress-program=xz \
    -C "$WORK_DIR" \
    "$PACKAGE_NAME_OVERRIDE"

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "  Packaging Complete"
echo "============================================================"
echo "Archive: $ARCHIVE_PATH"
echo "Size:    $(du -h "$ARCHIVE_PATH" | cut -f1)"
echo ""
echo "To install:"
echo "  tar xf $ARCHIVE_NAME"
echo "  cd $PACKAGE_NAME_OVERRIDE"
echo "  ./mixar"
echo ""
echo "To install desktop integration (optional):"
echo "  cp mixar.desktop ~/.local/share/applications/"
echo "  cp -r icons/* ~/.local/share/icons/hicolor/"
echo "  update-desktop-database ~/.local/share/applications/"
echo "============================================================"
