#!/bin/bash
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

set -euo pipefail

# Mixar Build Script
# Builds Blender (Release) + Mixar (configurable environment)

# Load all settings from settings.sh
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/settings.sh"

# Define build directory for this environment
BUILD_ENV_DIR="${BUILD_DIR}/${MIXAR_ENV}"

# Determine base path for embedded Python based on platform
if [[ "$PLATFORM" == "macOS" ]]; then
    PY_BASE="$BUILD_ENV_DIR/bin/${MIXAR_APP_NAME}.app/Contents/Resources"
elif [[ "$PLATFORM" == "Linux" ]]; then
    PY_BASE="$BUILD_ENV_DIR/bin"
else
    PY_BASE=""
fi

# Try common python binary names inside Blender's embedded Python
PYTHON_BIN=""
for candidate in \
    "$PY_BASE/5.0/python/bin/python${PYTHON_VERSION}" \
    "$PY_BASE/5.0/python/bin/python3" \
    "$PY_BASE/5.0/python/bin/python"; do
    if [[ -x "$candidate" ]]; then
        PYTHON_BIN="$candidate"
        break
    fi
done

SITE_PACKAGES="$PY_BASE/5.0/python/lib/python${PYTHON_VERSION}/site-packages"

if [[ -n "$PYTHON_BIN" ]]; then
    echo "Found Python binary: $PYTHON_BIN"

    # Determine platform-specific user preferences path
    if [[ "$PLATFORM" == "macOS" ]]; then
        USERPREF_PATH="$HOME/Library/Application Support/Mixar/5.0/config/mixar_userpref.blend"
    elif [[ "$PLATFORM" == "Linux" ]]; then
        USERPREF_PATH="${XDG_CONFIG_HOME:-$HOME/.config}/mixar/5.0/config/mixar_userpref.blend"
    else
        echo "Error: Unsupported platform '$PLATFORM' for theme generation"
        exit 1
    fi

    if [[ ! -f "$USERPREF_PATH" ]]; then
        echo "Error: User preferences file not found at: $USERPREF_PATH"
        exit 1
    fi

    cd "$SOURCE_DIR"/tools/utils
    "$PYTHON_BIN" blender_theme_as_c.py "$USERPREF_PATH"
    cd ../../..
    cp "$SOURCE_DIR"/release/datafiles/userdef/userdef_default_theme.c "$SRC_DIR"/release/datafiles/userdef/userdef_default_theme.c
else
    echo "Warning: Python binary not found under: $PY_BASE/5.0/python/bin"
fi

# Done
echo "=== Theme Generated Complete ==="