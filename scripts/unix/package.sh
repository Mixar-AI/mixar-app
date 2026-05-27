#!/bin/bash
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

set -euo pipefail

# =============================================================================
# Mixar macOS Packaging Script
# Signs, creates DMG, and notarizes the Mixar application bundle.
# Fully portable — uses a .p12 certificate file instead of system keychain.
#
# Usage:
#   ./package.sh [options]
#
# Required parameters (via flags or environment variables):
#   --cert-file       | CERT_FILE        Path to .p12 certificate file
#   --cert-password   | CERT_PASSWORD    Password for the .p12 file
#   --sign-id         | SIGN_ID          Developer ID Application identity
#   --team-id         | TEAM_ID          10-char Apple Team ID
#   --apple-id        | APPLE_ID         Apple ID email for notarization
#   --app-password    | APP_PASSWORD     App-specific password for notarization
#
# Optional parameters:
#   --app-path        | APP_PATH         Path to Mixar.app (default: from build dir)
#   --output-dir      | OUTPUT_DIR       Where to write the DMG (default: ./dist)
#   --dmg-name        | DMG_NAME         Override DMG filename
#   --icon-path       | ICON_PATH        Custom .icns for DMG volume icon
#   --skip-sign                          Skip codesigning (for testing)
#   --skip-notarize                      Skip notarization (for testing)
#   --entitlements    | ENTITLEMENTS     Path to entitlements.plist
#   --thumbnailer-entitlements | THUMBNAILER_ENTITLEMENTS  Path to thumbnailer entitlements
#   -h, --help                           Show this help message
#
# Environment file:
#   You can place all credentials in a .env file and pass it via --env-file.
#   The file should contain KEY=VALUE pairs (one per line).
#
# Export .p12 from source machine:
#   1. Open Keychain Access → find "Developer ID Application: ..." certificate
#   2. Right-click → Export Items → save as .p12 with a password
#   3. Copy the .p12 file to the target machine
# =============================================================================

# ── Resolve script and project paths ─────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/settings.sh"

RELEASE_DARWIN_DIR="$SOURCE_DIR/release/darwin"

# ── Defaults ─────────────────────────────────────────────────────────────────
BUILD_ENV_DIR="${BUILD_DIR}/${MIXAR_ENV}"
DEFAULT_APP_PATH="${BUILD_ENV_DIR}/bin/Mixar.app"
DEFAULT_ENTITLEMENTS="${RELEASE_DARWIN_DIR}/entitlements.plist"
DEFAULT_THUMBNAILER_ENTITLEMENTS="${RELEASE_DARWIN_DIR}/thumbnailer_entitlements.plist"
DEFAULT_ICON_PATH="${RELEASE_DARWIN_DIR}/Mixar.app/Contents/Resources/mixar_icon.icns"

# ── Parse arguments ──────────────────────────────────────────────────────────
SKIP_SIGN=false
SKIP_NOTARIZE=false
ENV_FILE=""

usage() {
    sed -n '/^# Usage:/,/^# =====/p' "$0" | sed 's/^# //' | sed 's/^#//'
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --cert-file)        CERT_FILE="$2"; shift 2 ;;
        --cert-password)    CERT_PASSWORD="$2"; shift 2 ;;
        --sign-id)          SIGN_ID="$2"; shift 2 ;;
        --team-id)          TEAM_ID="$2"; shift 2 ;;
        --apple-id)         APPLE_ID="$2"; shift 2 ;;
        --app-password)     APP_PASSWORD="$2"; shift 2 ;;
        --app-path)         APP_PATH="$2"; shift 2 ;;
        --output-dir)       OUTPUT_DIR="$2"; shift 2 ;;
        --dmg-name)         DMG_NAME="$2"; shift 2 ;;
        --icon-path)        ICON_PATH="$2"; shift 2 ;;
        --entitlements)     ENTITLEMENTS="$2"; shift 2 ;;
        --thumbnailer-entitlements) THUMBNAILER_ENTITLEMENTS="$2"; shift 2 ;;
        --env-file)         ENV_FILE="$2"; shift 2 ;;
        --skip-sign)        SKIP_SIGN=true; shift ;;
        --skip-notarize)    SKIP_NOTARIZE=true; shift ;;
        -h|--help)          usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

# ── Load env file if provided ────────────────────────────────────────────────
if [[ -n "$ENV_FILE" ]]; then
    if [[ ! -f "$ENV_FILE" ]]; then
        echo "Error: Environment file not found: $ENV_FILE"
        exit 1
    fi
    echo "Loading credentials from: $ENV_FILE"
    set -a
    source "$ENV_FILE"
    set +a
fi

# ── Resolve final variable values (flags > env vars > defaults) ──────────────
APP_PATH="${APP_PATH:-$DEFAULT_APP_PATH}"
OUTPUT_DIR="${OUTPUT_DIR:-${ROOT_DIR}/dist}"
ENTITLEMENTS="${ENTITLEMENTS:-$DEFAULT_ENTITLEMENTS}"
THUMBNAILER_ENTITLEMENTS="${THUMBNAILER_ENTITLEMENTS:-$DEFAULT_THUMBNAILER_ENTITLEMENTS}"
ICON_PATH="${ICON_PATH:-$DEFAULT_ICON_PATH}"

# Build version string and DMG name
ARCH="$(uname -m)"
VERSION="${MIXAR_VERSION}"
if [[ "$MIXAR_ENV" == "Prod" ]]; then
    DMG_NAME="${DMG_NAME:-Mixar-${VERSION}-${ARCH}.dmg}"
else
    DMG_NAME="${DMG_NAME:-Mixar-${VERSION}-${MIXAR_ENV}-${ARCH}.dmg}"
fi

# ── Validate prerequisites ───────────────────────────────────────────────────
validate() {
    local errors=0

    if [[ ! -d "$APP_PATH" ]]; then
        echo "Error: Mixar.app not found at: $APP_PATH"
        echo "  Run build.sh first, or pass --app-path <path>"
        errors=$((errors + 1))
    fi

    if [[ "$SKIP_SIGN" == false ]]; then
        if [[ -z "${CERT_FILE:-}" ]]; then
            echo "Error: --cert-file or CERT_FILE is required (path to .p12 certificate)"
            errors=$((errors + 1))
        elif [[ ! -f "${CERT_FILE:-}" ]]; then
            echo "Error: Certificate file not found: $CERT_FILE"
            errors=$((errors + 1))
        fi
        if [[ -z "${CERT_PASSWORD:-}" ]]; then
            echo "Error: --cert-password or CERT_PASSWORD is required (password for .p12 file)"
            errors=$((errors + 1))
        fi
        if [[ -z "${SIGN_ID:-}" ]]; then
            echo "Error: --sign-id or SIGN_ID is required for codesigning"
            errors=$((errors + 1))
        fi
        if [[ -z "${TEAM_ID:-}" ]]; then
            echo "Error: --team-id or TEAM_ID is required for codesigning"
            errors=$((errors + 1))
        fi
        if [[ ! -f "$ENTITLEMENTS" ]]; then
            echo "Error: Entitlements file not found: $ENTITLEMENTS"
            errors=$((errors + 1))
        fi
    fi

    if [[ "$SKIP_NOTARIZE" == false && "$SKIP_SIGN" == false ]]; then
        if [[ -z "${APPLE_ID:-}" ]]; then
            echo "Error: --apple-id or APPLE_ID is required for notarization"
            errors=$((errors + 1))
        fi
        if [[ -z "${APP_PASSWORD:-}" ]]; then
            echo "Error: --app-password or APP_PASSWORD is required for notarization"
            errors=$((errors + 1))
        fi
    fi

    if [[ $errors -gt 0 ]]; then
        echo ""
        echo "Pass --help for usage information, or use --env-file to load credentials."
        exit 1
    fi
}

validate

# ── Helper: print step headers ───────────────────────────────────────────────
step() {
    echo ""
    echo "=== $1 ==="
}

# ── Step 1: Prepare working copy ─────────────────────────────────────────────
step "Preparing application bundle"

WORK_DIR="$(mktemp -d)"
TEMP_KEYCHAIN=""
ORIGINAL_KEYCHAIN_LIST=""

cleanup() {
    # Restore original keychain search list and delete temp keychain
    if [[ -n "$TEMP_KEYCHAIN" && -f "$TEMP_KEYCHAIN" ]]; then
        echo "Cleaning up temporary keychain..."
        security delete-keychain "$TEMP_KEYCHAIN" 2>/dev/null || true
    fi
    if [[ -n "$ORIGINAL_KEYCHAIN_LIST" ]]; then
        eval security list-keychains -s "$ORIGINAL_KEYCHAIN_LIST"
    fi
    rm -rf "$WORK_DIR"
}
trap cleanup EXIT

echo "Copying Mixar.app to working directory..."
cp -R "$APP_PATH" "$WORK_DIR/Mixar.app"
WORK_APP="$WORK_DIR/Mixar.app"

echo "App bundle: $WORK_APP"

# ── Step 2: Set up temporary keychain and codesign ───────────────────────────
if [[ "$SKIP_SIGN" == true ]]; then
    step "Skipping codesigning (--skip-sign)"
else
    step "Setting up temporary keychain"

    # Save current keychain list so we can restore it on exit
    ORIGINAL_KEYCHAIN_LIST="$(security list-keychains -d user | tr -d '"' | tr '\n' ' ')"

    # Create a temporary keychain with a random password
    TEMP_KEYCHAIN="$WORK_DIR/mixar-packaging.keychain-db"
    TEMP_KC_PASSWORD="$(head -c 32 /dev/urandom | base64)"

    security create-keychain -p "$TEMP_KC_PASSWORD" "$TEMP_KEYCHAIN"
    # Keep it unlocked for the duration of signing
    security set-keychain-settings -lut 3600 "$TEMP_KEYCHAIN"
    security unlock-keychain -p "$TEMP_KC_PASSWORD" "$TEMP_KEYCHAIN"

    # Import the .p12 certificate into the temporary keychain
    echo "Importing certificate from: $CERT_FILE"
    security import "$CERT_FILE" \
        -k "$TEMP_KEYCHAIN" \
        -P "$CERT_PASSWORD" \
        -T /usr/bin/codesign \
        -T /usr/bin/security

    # Allow codesign to access the key without UI prompt
    security set-key-partition-list -S "apple-tool:,apple:,codesign:" \
        -s -k "$TEMP_KC_PASSWORD" "$TEMP_KEYCHAIN"

    # Add temp keychain to search list (prepend so it's found first)
    security list-keychains -d user -s "$TEMP_KEYCHAIN" $ORIGINAL_KEYCHAIN_LIST

    # Verify the identity is available
    echo "Verifying signing identity..."
    if ! security find-identity -v -p codesigning "$TEMP_KEYCHAIN" | grep -q "$TEAM_ID"; then
        echo "Error: Signing identity with team ID $TEAM_ID not found in certificate"
        echo "Available identities:"
        security find-identity -v -p codesigning "$TEMP_KEYCHAIN"
        exit 1
    fi
    echo "Signing identity found"

    step "Codesigning application bundle"

    # 2a. Find all Mach-O binaries that need signing
    echo "Scanning for unsigned Mach-O binaries..."
    UNSIGNED_LIST="$WORK_DIR/unsigned_files.txt"
    : > "$UNSIGNED_LIST"

    find "$WORK_APP" -type f -print0 | while IFS= read -r -d '' f; do
        # Skip non-Mach-O files
        file --brief "$f" | grep -q "Mach-O" || continue

        # Check if already signed with our team ID
        if codesign --verify --verbose=0 "$f" 2>/dev/null; then
            codesign -dvv "$f" 2>&1 | grep -q "TeamIdentifier=$TEAM_ID" && continue
        fi

        echo "$f" >> "$UNSIGNED_LIST"
    done

    UNSIGNED_COUNT=$(wc -l < "$UNSIGNED_LIST" | tr -d ' ')
    echo "Found $UNSIGNED_COUNT binaries to sign"

    # 2b. Sign individual binaries (inner-to-outer order)
    if [[ "$UNSIGNED_COUNT" -gt 0 ]]; then
        echo "Signing individual binaries..."
        while IFS= read -r binary; do
            [[ -z "$binary" ]] && continue
            codesign --remove-signature "$binary" 2>/dev/null || true
            codesign --force --timestamp --options runtime \
                     --keychain "$TEMP_KEYCHAIN" \
                     --sign "$SIGN_ID" "$binary"
            echo "  Signed: ${binary#"$WORK_APP/"}"
        done < "$UNSIGNED_LIST"
    fi

    # 2c. Sign the thumbnailer appex if present
    THUMBNAILER_APPEX="$WORK_APP/Contents/PlugIns/mixar-thumbnailer.appex"
    if [[ -d "$THUMBNAILER_APPEX" ]]; then
        echo "Signing thumbnailer extension..."
        codesign --force --deep --timestamp --options runtime \
                 --keychain "$TEMP_KEYCHAIN" \
                 --entitlements "$THUMBNAILER_ENTITLEMENTS" \
                 --sign "$SIGN_ID" "$THUMBNAILER_APPEX"
    fi

    # 2d. Sign the top-level app bundle with entitlements
    echo "Signing Mixar.app bundle..."
    codesign --force --deep --timestamp --options runtime \
             --keychain "$TEMP_KEYCHAIN" \
             --entitlements "$ENTITLEMENTS" \
             --sign "$SIGN_ID" "$WORK_APP"

    # 2e. Verify
    echo "Verifying signature..."
    codesign --verify --deep --strict --verbose=2 "$WORK_APP"
    echo "Signature verification passed"
fi

# ── Step 3: Create DMG ───────────────────────────────────────────────────────
step "Creating DMG: $DMG_NAME"

mkdir -p "$OUTPUT_DIR"

# Create staging folder with versioned app bundle + Applications symlink
DMG_STAGING="$WORK_DIR/dmg_staging"
MIXAR_MAJOR="$(echo "$MIXAR_VERSION" | cut -d. -f1)"
MIXAR_MINOR="$(echo "$MIXAR_VERSION" | cut -d. -f2)"
VERSIONED_APP_NAME="Mixar ${MIXAR_MAJOR}.${MIXAR_MINOR}.app"
mkdir -p "$DMG_STAGING"
mv "$WORK_APP" "$DMG_STAGING/$VERSIONED_APP_NAME"
ln -s /Applications "$DMG_STAGING/Applications"

# Create the DMG
DMG_PATH="$OUTPUT_DIR/$DMG_NAME"
hdiutil create \
    -volname "Mixar ${MIXAR_MAJOR}.${MIXAR_MINOR}" \
    -srcfolder "$DMG_STAGING" \
    -ov \
    -format UDZO \
    "$DMG_PATH"

echo "DMG created: $DMG_PATH"

# Set volume icon if fileicon is available
if [[ -f "$ICON_PATH" ]]; then
    if command -v fileicon >/dev/null 2>&1; then
        echo "Setting DMG volume icon..."
        fileicon set "$DMG_PATH" "$ICON_PATH"
    else
        echo "Warning: 'fileicon' not installed — DMG will use default icon"
        echo "  Install via: brew install fileicon"
    fi
fi

# ── Step 4: Sign DMG ─────────────────────────────────────────────────────────
if [[ "$SKIP_SIGN" == true ]]; then
    step "Skipping DMG signing (--skip-sign)"
else
    step "Signing DMG"
    codesign --force --timestamp --keychain "$TEMP_KEYCHAIN" --sign "$SIGN_ID" "$DMG_PATH"
    echo "DMG signed"
fi

# ── Step 5: Notarize ─────────────────────────────────────────────────────────
if [[ "$SKIP_SIGN" == true || "$SKIP_NOTARIZE" == true ]]; then
    step "Skipping notarization"
else
    step "Submitting DMG for notarization"

    # Use --apple-id and --password flags directly (no keychain profile needed)
    xcrun notarytool submit "$DMG_PATH" \
        --apple-id "$APPLE_ID" \
        --password "$APP_PASSWORD" \
        --team-id "$TEAM_ID" \
        --wait

    step "Stapling notarization ticket"
    xcrun stapler staple "$DMG_PATH"
    echo "Notarization complete"
fi

# ── Done ─────────────────────────────────────────────────────────────────────
step "Packaging complete"
echo "Output: $DMG_PATH"
echo "Size:   $(du -h "$DMG_PATH" | cut -f1)"
