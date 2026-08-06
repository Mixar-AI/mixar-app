#!/bin/bash
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

set -euo pipefail

# One-time macOS developer setup: create a stable self-signed code-signing
# identity for local Mixar builds.
#
# Why: `make build` produces an ad-hoc signed binary whose code-signing
# identity is the binary's own hash, so every rebuild looks like a brand-new
# app to the macOS Keychain. The login tokens Mixar stores under the
# "MixarSafeStorage" Keychain service are ACL-bound to the app that wrote
# them, so each rebuild triggers the "Mixar wants your confidential
# information stored in keychain" SecurityAgent prompt and "Always Allow"
# never persists. Signing every build with the SAME certificate makes the
# Keychain match by certificate instead of per-build hash — one "Always
# Allow" then holds forever.
#
# Usage:
#   ./scripts/unix/setup_dev_codesign.sh [cert-name]   # default: "Mixar Dev"
#
# Then add to your .env:
#   MIXAR_DEV_SIGN_ID="Mixar Dev"
#
# build.sh picks it up and re-signs the built app automatically. This is a
# LOCAL DEV convenience only — release signing (Developer ID, notarization)
# lives in scripts/unix/package.sh and is unaffected.

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "Error: this script is macOS-only." >&2
    exit 1
fi

CERT_NAME="${1:-Mixar Dev}"
LOGIN_KEYCHAIN="$HOME/Library/Keychains/login.keychain-db"

# ── Already set up? ──────────────────────────────────────────────────────────
if security find-identity -v -p codesigning 2>/dev/null | grep -qF "\"$CERT_NAME\""; then
    echo "Code-signing identity \"$CERT_NAME\" already exists — nothing to do."
    echo "Make sure your .env contains: MIXAR_DEV_SIGN_ID=\"$CERT_NAME\""
    exit 0
fi

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

echo "Creating self-signed code-signing certificate \"$CERT_NAME\"..."

# ── Generate key + certificate with the Code Signing EKU ─────────────────────
cat > "$WORK_DIR/cert.cnf" << EOF
[req]
distinguished_name = dn
x509_extensions = ext
prompt = no
[dn]
CN = $CERT_NAME
[ext]
keyUsage = critical,digitalSignature
extendedKeyUsage = critical,codeSigning
basicConstraints = critical,CA:false
EOF

openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes \
    -keyout "$WORK_DIR/key.pem" -out "$WORK_DIR/cert.pem" \
    -config "$WORK_DIR/cert.cnf" > /dev/null 2>&1

# ── Import into the login keychain, allowing codesign to use the key ─────────
# Key and cert are imported as separate PEMs rather than a PKCS#12 bundle:
# OpenSSL 3.x (e.g. Homebrew) exports p12 with AES/SHA-256 defaults the macOS
# Security framework cannot parse ("MAC verification failed" on import).
security import "$WORK_DIR/key.pem" -k "$LOGIN_KEYCHAIN" -T /usr/bin/codesign
security import "$WORK_DIR/cert.pem" -k "$LOGIN_KEYCHAIN"

# ── Trust the cert for code signing (user domain) ────────────────────────────
# macOS shows a one-time authorization dialog here — that is expected.
echo "Marking the certificate as trusted for code signing"
echo "(macOS will ask for your login password once)..."
if ! security add-trusted-cert -p codeSign -k "$LOGIN_KEYCHAIN" "$WORK_DIR/cert.pem"; then
    cat >&2 << EOF

Warning: could not set trust settings automatically.
Open Keychain Access, find "$CERT_NAME" in the login keychain,
double-click it, expand "Trust" and set Code Signing to "Always Trust".
EOF
fi

# ── Let codesign use the private key without a per-build prompt ──────────────
# Keys imported via `security import` are partition-list restricted on
# modern macOS; without this, the FIRST codesign use pops a
# "codesign wants to sign using key" dialog (clicking "Always Allow"
# there also works — this just avoids it).
echo "Authorizing codesign to use the key (enter your login password if asked)..."
security set-key-partition-list -S "apple-tool:,apple:,codesign:" \
    "$LOGIN_KEYCHAIN" > /dev/null || \
    echo "Note: could not update key partition list — the first build may show" \
         "one 'codesign wants to sign' prompt; click 'Always Allow'."

echo
echo "Done. Identity created:"
security find-identity -v -p codesigning | grep -F "\"$CERT_NAME\"" || true
cat << EOF

Next steps:
  1. Add this line to your .env (copy .env.example if you have none):
       MIXAR_DEV_SIGN_ID="$CERT_NAME"
  2. Run: make build
  3. Launch Mixar. When the Keychain prompt appears ONE last time,
     click "Always Allow". It will never ask again — the certificate
     identity is stable across rebuilds.
EOF
