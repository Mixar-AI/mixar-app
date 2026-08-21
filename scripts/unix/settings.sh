#!/bin/bash
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

# Mixar Application Settings
# Source this file in scripts that need these settings
#
# Configuration priority:
#   1. Environment variables (already set, e.g. from CI or parent shell)
#   2. .env file in repo root (local dev overrides)
#   3. Hardcoded defaults below

# Get the root directory relative to this settings.sh script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
export ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Load .env if it exists (local dev overrides)
ENV_FILE="$ROOT_DIR/.env"
if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi

# Version always comes from VERSION file (canonical source)
if [ -z "${MIXAR_VERSION:-}" ]; then
    VERSION_FILE="$ROOT_DIR/VERSION"
    if [ -f "$VERSION_FILE" ]; then
        export MIXAR_VERSION="$(cat "$VERSION_FILE" | tr -d '[:space:]')"
    else
        export MIXAR_VERSION="0.0.0"
    fi
fi

# Core environment settings (env var > .env > default)
export MIXAR_ENV="${MIXAR_ENV:-Prod}"
export MIXAR_BACKEND_URL="${MIXAR_BACKEND_URL:-https://api.mixar.app}"
export MIXAR_FRONTEND_URL="${MIXAR_FRONTEND_URL:-https://www.mixar.app}"

# App info (constants)
export MIXAR_VERSION_PATCH="${MIXAR_VERSION_PATCH:-0}"
export MIXAR_APP_NAME="${MIXAR_APP_NAME:-Mixar}"
export MIXAR_EXECUTABLE_NAME="${MIXAR_EXECUTABLE_NAME:-mixar}"
export MIXAR_DESCRIPTION="${MIXAR_DESCRIPTION:-AI Native 3D Content Creation Software}"
export MIXAR_VENDOR="${MIXAR_VENDOR:-Mixar}"
export MIXAR_WEBSITE="${MIXAR_WEBSITE:-https://mixar.app}"

# Bundle settings (constants)
export MIXAR_BUNDLE_IDENTIFIER="${MIXAR_BUNDLE_IDENTIFIER:-com.mixar.mixar}"
export MIXAR_BUNDLE_COPYRIGHT="${MIXAR_BUNDLE_COPYRIGHT:-© 2025 Mixar}"

# Build settings (constants)
export BLENDER_VERSION="${BLENDER_VERSION:-5.2}"
export PYTHON_VERSION="${PYTHON_VERSION:-3.13}"
export REQUIRED_CMAKE_VERSION="${REQUIRED_CMAKE_VERSION:-3.16}"

# Directory Structure
export BUILD_DIR="${ROOT_DIR}/build"
export SOURCE_DIR="${ROOT_DIR}/source"
export SRC_DIR="${ROOT_DIR}/src"
export CMAKE_DIR="${ROOT_DIR}/cmake"

# Upstream Blender tree (multi-GB, gitignored — populated once per machine).
# Linked git worktrees don't carry ignored files, so a worktree checkout has
# no upstream/ of its own. Resolution order:
#   1. MIXAR_UPSTREAM_DIR (env / .env override)
#   2. this checkout's own upstream/ (a real tree, not an empty dir)
#   3. the main checkout's upstream/ (worktrees share it — overlay.sh only
#      ever READS from $UPSTREAM_DIR, so sharing is safe)
if [ -n "${MIXAR_UPSTREAM_DIR:-}" ]; then
    export UPSTREAM_DIR="$MIXAR_UPSTREAM_DIR"
elif [ -f "${ROOT_DIR}/upstream/CMakeLists.txt" ]; then
    export UPSTREAM_DIR="${ROOT_DIR}/upstream"
else
    _git_common_dir="$(git -C "$ROOT_DIR" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
    _main_checkout_root="${_git_common_dir%/.git}"
    if [ -n "$_git_common_dir" ] && [ -f "${_main_checkout_root}/upstream/CMakeLists.txt" ]; then
        export UPSTREAM_DIR="${_main_checkout_root}/upstream"
        echo "Worktree checkout: sharing upstream from main checkout: $UPSTREAM_DIR" >&2
        # upstream is a submodule pinned per branch — warn (don't fail) when
        # the shared tree isn't at the commit THIS branch pins, so a silent
        # wrong-revision build can't sneak past.
        _pinned="$(git -C "$ROOT_DIR" rev-parse HEAD:upstream 2>/dev/null || true)"
        _actual="$(git -C "$UPSTREAM_DIR" rev-parse HEAD 2>/dev/null || true)"
        if [ -n "$_pinned" ] && [ -n "$_actual" ] && [ "$_pinned" != "$_actual" ]; then
            echo "WARNING: shared upstream is at ${_actual:0:12} but this branch pins ${_pinned:0:12}." >&2
            echo "         Update it (git -C \"$UPSTREAM_DIR\" checkout $_pinned) or set MIXAR_UPSTREAM_DIR." >&2
        fi
        unset _pinned _actual
    else
        # No usable upstream anywhere — keep the default path so the
        # overlay's error message points at the expected location.
        export UPSTREAM_DIR="${ROOT_DIR}/upstream"
    fi
    unset _git_common_dir _main_checkout_root
fi

# Platform-specific settings
if [[ "$OSTYPE" == "darwin"* ]]; then
    export PLATFORM="macOS"
    DEFAULT_CORES=$(sysctl -n hw.ncpu)
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    export PLATFORM="Linux"
    DEFAULT_CORES=$(nproc)
else
    export PLATFORM="Unknown"
    DEFAULT_CORES=4
fi

# Build optimization - define BUILD_CORES before using it
export BUILD_CORES=${BUILD_CORES:-$DEFAULT_CORES}

# Platform-specific build settings (now that BUILD_CORES is defined)
if [[ "$PLATFORM" == "macOS" ]]; then
    # macOS-specific settings
    export CMAKE_GENERATOR_ARGS=""  # Use default (Xcode or Make)
    export BUILD_ARGS="--parallel $BUILD_CORES --config \$CMAKE_BUILD_TYPE"
    # Pin the SDK to the selected Xcode's macOS SDK. Without this, clang's
    # default sysroot can resolve to /Library/Developer/CommandLineTools/SDKs
    # when the CLT ships a newer SDK than Xcode.app; CMake then caches
    # find_library() framework hits (Metal, Security, zlib, ...) inside the
    # CLT SDK and emits explicit -F paths that demote those headers from
    # system to user headers, turning -Werror=unguarded-availability-new into
    # hard build failures in Cycles' Metal device code.
    if [[ -z "${SDKROOT:-}" ]]; then
        SDKROOT="$(xcrun --sdk macosx --show-sdk-path 2>/dev/null || true)"
        if [[ -n "$SDKROOT" ]]; then
            export SDKROOT
        else
            unset SDKROOT
        fi
    fi
elif [[ "$PLATFORM" == "Linux" ]]; then
    # Linux-specific settings
    export CMAKE_GENERATOR_ARGS=""  # Use default (Make or Ninja)
    export BUILD_ARGS="--parallel $BUILD_CORES --verbose"
else
    # Generic fallback settings
    export CMAKE_GENERATOR_ARGS=""
    export BUILD_ARGS="--parallel $BUILD_CORES"
fi
