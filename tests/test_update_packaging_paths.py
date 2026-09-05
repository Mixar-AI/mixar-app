# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Install paths must not carry a version.

Restart-to-update assumes a release replaces the previous one. A
version-stamped install directory (Windows) or bundle name (macOS) breaks
that quietly: the new build lands beside the old one and the user keeps
launching whichever shortcut they had. These are cheap source-level
guards on the two places that decide those names.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGING_CMAKE = ROOT / "src" / "build_files" / "cmake" / "packaging.cmake"
WIX_TEMPLATE = ROOT / "src" / "release" / "windows" / "installer_wix" / "WIX.template"
PACKAGE_SH = ROOT / "scripts" / "unix" / "package.sh"


def _cmake() -> str:
    return PACKAGING_CMAKE.read_text(encoding="utf-8")


def _windows_block() -> str:
    """The if(WIN32) section — an earlier generic assignment is overridden."""
    block = _cmake()
    return block[block.index("if(WIN32)"):]


def test_windows_install_directory_has_no_version():
    match = re.search(
        r'set\(CPACK_PACKAGE_INSTALL_DIRECTORY\s+"([^"]*)"\)', _windows_block(),
    )
    assert match, "CPACK_PACKAGE_INSTALL_DIRECTORY not found"
    assert match.group(1) == "Mixar"
    assert "MAJOR_VERSION" not in match.group(1)


def test_windows_upgrade_code_is_version_independent():
    """The UpgradeCode is the product identity — deriving it from a version
    turns every minor release into a side-by-side install."""
    block = _cmake()
    guid_call = block[block.index("string(UUID CPACK_WIX_UPGRADE_GUID"):]
    guid_call = guid_call[:guid_call.index(")")]

    assert 'NAME "Mixar"' in guid_call
    assert "VERSION" not in guid_call


def test_legacy_upgrade_codes_are_generated_and_referenced():
    block = _cmake()

    assert "MIXAR_LEGACY_UPGRADE_XML" in block
    assert 'NAME "Mixar/Mixar ${_legacy_major}.${_legacy_minor}"' in block
    assert "mixar_legacy_upgrades.wxs" in block
    assert "MIXAR_LEGACY_UPGRADES_WXS" in block
    # A WiX Fragment is dead code unless something references it.
    assert 'MIXAR_LEGACY_UPGRADE_MARKER' in WIX_TEMPLATE.read_text(encoding="utf-8")


def test_legacy_upgrades_remove_rather_than_only_detect():
    assert 'OnlyDetect=\\"no\\"' in _cmake()


def test_macos_dmg_bundle_name_has_no_version():
    source = PACKAGE_SH.read_text(encoding="utf-8")

    assert 'APP_BUNDLE_NAME="Mixar.app"' in source
    assert "VERSIONED_APP_NAME" not in source
    assert 'mv "$WORK_APP" "$DMG_STAGING/$APP_BUNDLE_NAME"' in source
