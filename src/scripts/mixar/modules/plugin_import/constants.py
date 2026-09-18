# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Constants for the plugin_import module.

All module constants live here per the project code rules. Nothing in
this file imports ``bpy`` so the discovery/enumeration logic stays
unit-testable outside Blender.
"""

from __future__ import annotations

# Subfolders (relative to a Blender version config dir) that hold the
# two kinds of user-installed plugins.
ADDONS_SUBDIR = "scripts/addons"
EXTENSIONS_SUBDIR = "extensions"

# Marker file that identifies an unpacked extension package on disk.
EXTENSION_MANIFEST = "blender_manifest.toml"

# Module-id prefix for extensions. The full enable id is
# ``bl_ext.<repo_module>.<pkg_id>``.
EXTENSION_MODULE_PREFIX = "bl_ext"

# Default local user extension repo module name. Extensions copied in
# without an explicit repo land here.
DEFAULT_USER_REPO = "user_default"

# Directory / file names to skip while scanning addon and extension
# trees (caches, repo metadata, non-plugin housekeeping).
SCAN_SKIP_NAMES = frozenset(
    {
        "__pycache__",
        ".DS_Store",
        "addons_contrib",
        ".blender_ext",  # extension repo cache dir
    }
)

# Plugin kinds (stored on PluginItem.kind / PluginInfo.kind).
KIND_ADDON = "addon"
KIND_EXTENSION = "extension"

# Per-plugin import outcome codes (returned by the importer).
STATUS_IMPORTED = "imported"      # files copied in fresh
STATUS_EXISTS = "exists"          # already present in Mixar, left as-is
STATUS_FAILED = "failed"          # copy raised

# Per-plugin enable outcome codes.
ENABLE_OK = "enabled"
ENABLE_SKIPPED = "skipped"        # user left the checkbox off
ENABLE_FAILED = "enable_failed"   # enable raised (e.g. API incompatible)


# ---------------------------------------------------------------------------
# Source (vanilla Blender) config roots per platform.
# ---------------------------------------------------------------------------
# Each value is a list of *base* directories that directly contain the
# per-version folders (e.g. ".../Blender/4.5"). Resolved lazily against
# the environment in core/discovery.py so this file stays bpy-free.

# macOS: ~/Library/Application Support/Blender
MACOS_BLENDER_BASE = ("Library", "Application Support", "Blender")

# Windows: %APPDATA%\Blender Foundation\Blender
WINDOWS_BLENDER_BASE = ("Blender Foundation", "Blender")

# Linux (XDG): ~/.config/blender
LINUX_BLENDER_BASE = (".config", "blender")
