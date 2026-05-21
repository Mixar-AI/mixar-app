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
export BLENDER_VERSION="${BLENDER_VERSION:-5.0}"
export PYTHON_VERSION="${PYTHON_VERSION:-3.11}"
export REQUIRED_CMAKE_VERSION="${REQUIRED_CMAKE_VERSION:-3.16}"

# Directory Structure
export BUILD_DIR="${ROOT_DIR}/build"
export SOURCE_DIR="${ROOT_DIR}/source"
export SRC_DIR="${ROOT_DIR}/src"
export CMAKE_DIR="${ROOT_DIR}/cmake"
export UPSTREAM_DIR="${ROOT_DIR}/upstream"

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
elif [[ "$PLATFORM" == "Linux" ]]; then
    # Linux-specific settings
    export CMAKE_GENERATOR_ARGS=""  # Use default (Make or Ninja)
    export BUILD_ARGS="--parallel $BUILD_CORES --verbose"
else
    # Generic fallback settings
    export CMAKE_GENERATOR_ARGS=""
    export BUILD_ARGS="--parallel $BUILD_CORES"
fi
