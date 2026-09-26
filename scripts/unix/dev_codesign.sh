#!/bin/bash
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later
#
# Re-sign a local macOS build with the stable dev identity so the Keychain
# "Always Allow" for the MixarSafeStorage login tokens persists across
# rebuilds (see setup_dev_codesign.sh for the why). Opt-in through
# MIXAR_DEV_SIGN_ID in .env; a no-op elsewhere or when unset.
#
# Called by build.sh AND install.sh: the CMake install target re-copies the
# executable and leaves it ad-hoc (linker) signed, which silently undid the
# build-time signature — every `make install` was a brand-new app to Keychain.
#
# Usage: dev_codesign.sh <path/to/Mixar.app/Contents/MacOS/Mixar>
set -euo pipefail

BINARY="${1:?usage: dev_codesign.sh <Mixar executable>}"
if [[ "$(uname -s)" != "Darwin" || -z "${MIXAR_DEV_SIGN_ID:-}" ]]; then
    exit 0
fi
if [[ ! -x "$BINARY" ]]; then
    echo "dev_codesign: no executable at $BINARY" >&2
    exit 0
fi

# get-task-allow keeps the binary attachable by lldb, matching what an
# ad-hoc dev signature allows.
ENTITLEMENTS="$(dirname "$BINARY")/../../../dev_codesign_entitlements.plist"
cat > "$ENTITLEMENTS" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>com.apple.security.get-task-allow</key>
    <true/>
</dict>
</plist>
PLIST

echo "Signing dev build with identity: $MIXAR_DEV_SIGN_ID"
if codesign --force --sign "$MIXAR_DEV_SIGN_ID" --entitlements "$ENTITLEMENTS" "$BINARY"; then
    echo "Dev codesign OK — Keychain 'Always Allow' will persist across rebuilds."
else
    echo "Warning: dev codesign failed. The build is still usable, but Keychain"
    echo "will re-prompt after every rebuild. Create the identity with:"
    echo "  ./scripts/unix/setup_dev_codesign.sh"
fi
