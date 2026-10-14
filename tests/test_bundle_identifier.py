# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The macOS bundle identifier is never versioned.

Every Keychain item's access list is bound to the app's code-signing
identity, which embeds the bundle id. `com.mixar.mixar-4-2` → `-4-3` made
each minor release a new app to the Keychain: one "Mixar wants to access…"
dialog per stored credential on every upgrade, and a data-protection
keychain access group that no later release could open.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CMAKE = (
    ROOT / "src" / "source" / "creator" / "CMakeLists.txt",
    ROOT / "src" / "build_files" / "cmake" / "platform" / "platform_apple.cmake",
)


def test_bundle_identifier_carries_no_version():
    for path in CMAKE:
        src = path.read_text(encoding="utf-8")
        assert "com.mixar.mixar-${" not in src, path
        for match in re.finditer(r'(MACOSX_BUNDLE_GUI_IDENTIFIER|PRODUCT_BUNDLE_IDENTIFIER)\s+"([^"]+)"', src):
            assert match.group(2) == "com.mixar.mixar", (path, match.group(0))
    # Only the display name carries the version.
    creator = CMAKE[0].read_text(encoding="utf-8")
    assert 'MACOSX_BUNDLE_BUNDLE_NAME "Mixar ${_MIXAR_MAJOR}.${_MIXAR_MINOR}"' in creator
