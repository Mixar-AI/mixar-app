#!/bin/bash
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

set -euo pipefail

# =============================================================================
# Mixar macOS Release Script
# Runs a clean build, packages the app (sign + DMG + notarize), and uploads
# the resulting DMG to S3.
#
# Usage:
#   ./release.sh [options]
#
# Options:
#   --env-file <path>     Signing credentials file (passed to package.sh)
#   --skip-sign           Skip codesigning (passed to package.sh)
#   --skip-notarize       Skip notarization (passed to package.sh)
#   --skip-upload         Skip S3 upload
#   -h, --help            Show this help message
#
# Environment variables (for S3 upload):
#   S3_BUCKET             S3 bucket name (required unless --skip-upload)
#   S3_PREFIX             S3 base prefix (default: releases/), version is appended
#
# Environment variables (for signing, can also use --env-file):
#   CERT_FILE             Path to .p12 certificate file
#   CERT_PASSWORD         Password for the .p12 file
#   SIGN_ID               Developer ID Application identity
#   TEAM_ID               10-char Apple Team ID
#   APPLE_ID              Apple ID email for notarization
#   APP_PASSWORD           App-specific password for notarization
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Parse arguments ──────────────────────────────────────────────────────────
PACKAGE_ARGS=()
SKIP_UPLOAD=false

usage() {
    sed -n '/^# Usage:/,/^# =====/p' "$0" | sed 's/^# //' | sed 's/^#//'
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-upload)   SKIP_UPLOAD=true; shift ;;
        --env-file)      PACKAGE_ARGS+=("--env-file" "$2"); shift 2 ;;
        --skip-sign)     PACKAGE_ARGS+=("--skip-sign"); shift ;;
        --skip-notarize) PACKAGE_ARGS+=("--skip-notarize"); shift ;;
        -h|--help)       usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

# ── Load settings for version/env info ───────────────────────────────────────
source "$SCRIPT_DIR/settings.sh"

# Build the artifact filename — must match package.sh naming convention:
#   Prod  → Mixar-{version}-{arch}.dmg
#   Other → Mixar-{version}-{env}-{arch}.dmg
ARCH="$(uname -m)"
if [[ "$MIXAR_ENV" == "Prod" ]]; then
    DMG_NAME="Mixar-${MIXAR_VERSION}-${ARCH}.dmg"
else
    DMG_NAME="Mixar-${MIXAR_VERSION}-${MIXAR_ENV}-${ARCH}.dmg"
fi
export DMG_NAME
DMG_PATH="${ROOT_DIR}/dist/${DMG_NAME}"
S3_PREFIX="${S3_PREFIX:-releases/}${MIXAR_VERSION}/"

echo "============================================================"
echo "  Mixar Release"
echo "============================================================"
echo "  Version     : ${MIXAR_VERSION}"
echo "  Environment : ${MIXAR_ENV}"
echo "  Architecture: ${ARCH}"
echo "  Output      : ${DMG_PATH}"
if [[ "$SKIP_UPLOAD" == false ]]; then
    echo "  S3 dest     : s3://${S3_BUCKET:-<not set>}/${S3_PREFIX}${DMG_NAME}"
fi
echo "============================================================"
echo ""

# ── Step 1: Clean Build ──────────────────────────────────────────────────────
echo "=== [1/3] Clean Build ==="
"$SCRIPT_DIR/build_clean.sh" --yes
echo ""

# ── Step 2: Package ──────────────────────────────────────────────────────────
echo "=== [2/3] Packaging ==="

if [[ ${#PACKAGE_ARGS[@]} -gt 0 ]]; then
    "$SCRIPT_DIR/package.sh" "${PACKAGE_ARGS[@]}"
else
    "$SCRIPT_DIR/package.sh"
fi

if [[ ! -f "$DMG_PATH" ]]; then
    echo "Error: Expected DMG not found at: $DMG_PATH"
    echo "Contents of dist/:"
    ls -la "${ROOT_DIR}/dist/" 2>/dev/null || echo "  (directory does not exist)"
    exit 1
fi
echo ""

# ── Step 3: Upload to S3 ─────────────────────────────────────────────────────
if [[ "$SKIP_UPLOAD" == true ]]; then
    echo "=== [3/3] Skipping S3 upload (--skip-upload) ==="
else
    echo "=== [3/3] Uploading to S3 ==="

    if [[ -z "${S3_BUCKET:-}" ]]; then
        echo "Error: S3 bucket not specified."
        echo "  Set the S3_BUCKET environment variable."
        exit 1
    fi

    if ! command -v aws &>/dev/null; then
        echo "Error: AWS CLI not found. Install it from https://aws.amazon.com/cli/"
        exit 1
    fi

    S3_DEST="s3://${S3_BUCKET}/${S3_PREFIX}${DMG_NAME}"
    echo "Uploading: ${DMG_PATH}"
    echo "      To: ${S3_DEST}"

    aws s3 cp "$DMG_PATH" "$S3_DEST"
    echo "Upload complete."
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "  Release Complete"
echo "============================================================"
echo "  DMG : ${DMG_PATH}"
echo "  Size: $(du -h "$DMG_PATH" | cut -f1)"
if [[ "$SKIP_UPLOAD" == false && -n "${S3_BUCKET:-}" ]]; then
    echo "  S3  : ${S3_DEST}"
fi
echo "============================================================"
