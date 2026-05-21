#!/bin/bash
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

set -euo pipefail

# Mixar Clean Build Script
# Deletes environment-specific build directory and source directory, then runs a fresh build
#
# Usage:
#   ./build_clean.sh          Interactive (prompts for confirmation)
#   ./build_clean.sh --yes    Non-interactive (skips confirmation, for CI/release scripts)

# Load all settings from settings.sh
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/settings.sh"

# Environment-specific build directory (e.g., build/Prod, build/Dev)
BUILD_ENV_DIR="${BUILD_DIR}/${MIXAR_ENV}"

# Parse --yes flag for non-interactive mode
AUTO_CONFIRM=false
if [[ "${1:-}" == "--yes" || "${1:-}" == "-y" ]]; then
    AUTO_CONFIRM=true
fi

echo "=== Clean Build Starting ==="
echo "This will delete the following directories:"
echo "  - Build (${MIXAR_ENV}): $BUILD_ENV_DIR"
echo "  - Source: $SOURCE_DIR"
echo ""

# Prompt for confirmation (skip if --yes)
if [[ "$AUTO_CONFIRM" == false ]]; then
    read -p "Are you sure you want to proceed? (y/N) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 1
    fi
fi

# Delete environment-specific build directory
if [ -d "$BUILD_ENV_DIR" ]; then
    echo "Deleting build directory: $BUILD_ENV_DIR"
    rm -rf "$BUILD_ENV_DIR"
    echo "Build directory deleted."
else
    echo "Build directory does not exist, skipping."
fi

# Delete source directory
if [ -d "$SOURCE_DIR" ]; then
    echo "Deleting source directory: $SOURCE_DIR"
    rm -rf "$SOURCE_DIR"
    echo "Source directory deleted."
else
    echo "Source directory does not exist, skipping."
fi

echo ""
echo "=== Starting Fresh Build ==="

# Run the build script
"$SCRIPT_DIR/build.sh"
