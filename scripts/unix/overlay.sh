#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

set -euo pipefail

# Load all settings from settings.sh
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/settings.sh"

echo "Clearing previous source directory..."
cd "$ROOT_DIR"
rm -rf "$SOURCE_DIR"
mkdir -p "$SOURCE_DIR"

echo "Copying upstream to source..."
# Exclude all git-related files and folders
rsync -a \
    --exclude='.git/' \
    --exclude='.gitignore' \
    --exclude='.gitmodules' \
    --exclude='.gitattributes' \
    --exclude='.github/' \
    --exclude='.gitkeep' \
    --exclude='.vscode/' \
    --exclude='.idea/' \
    --exclude='.gitea/' \
    "$UPSTREAM_DIR/" "$SOURCE_DIR/"

# Check for upstream conflicts before overlaying
if [ -f "$ROOT_DIR/.overlay_manifest" ]; then
    echo "Checking for upstream overlay conflicts..."
    if ! "$SCRIPT_DIR/check_overlay_conflicts.sh" --check; then
        echo "WARNING: Upstream conflicts detected. Continuing build anyway."
        echo "Run 'scripts/unix/check_overlay_conflicts.sh --generate' after resolving."
    fi
fi

echo "Overlaying Mixar sources onto source..."
# Skip local-only artefacts that git ignores but that live inside src/ on a
# dev machine (a stray .venv, .pyc caches, Finder metadata). CMake's install
# rule for scripts/ only filters __pycache__, so anything else copied here
# would ship inside the app bundle.
rsync -av \
    --exclude='.venv/' \
    --exclude='venv/' \
    --exclude='__pycache__/' \
    --exclude='.pytest_cache/' \
    --exclude='.DS_Store' \
    "$SRC_DIR/" "$SOURCE_DIR/"

echo "Overlay complete."