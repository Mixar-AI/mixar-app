#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

# First argument selects the build environment folder (defaults to Dev).
BUILD_ENV="${1:-Dev}"

case "$(uname -s)" in
    Darwin)
        BINARY="$ROOT_DIR/build/$BUILD_ENV/bin/Mixar.app/Contents/MacOS/Mixar"
        ;;
    Linux)
        BINARY="$ROOT_DIR/build/$BUILD_ENV/bin/mixar"
        ;;
    *)
        echo "Error: unsupported platform: $(uname -s)" >&2
        exit 1
        ;;
esac

if [[ ! -x "$BINARY" ]]; then
	echo "Error: Mixar binary not found at:" >&2
	echo "  $BINARY" >&2
	echo "Make sure ./build/$BUILD_ENV exists and is built." >&2
	exit 1
fi

echo "Launching Mixar from build/$BUILD_ENV..."
shift || true
if [[ "$(uname -s)" == Darwin ]]; then
    exec open -n -W "$ROOT_DIR/build/$BUILD_ENV/bin/Mixar.app" --args "$@"
fi
exec "$BINARY" "$@"
