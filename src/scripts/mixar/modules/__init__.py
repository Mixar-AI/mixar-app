# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar Modules

Contains feature modules for the Mixar application.

Available modules:
- common: Shared components (mode selector, utilities)
- moodboard: Moodboard mode for image collection and AI generation
- space_mixie: Mixie space with segmentation, lookdev, and image generation
- paint: Texture painting backend (layer system, nodes, baking, texturing workspace)
- testing: Testing utilities and test files

Registration is handled by bootstrap/__init__.py which auto-discovers
and registers all files in modules/**/ui/ directories.
Paint module registration is handled by bootstrap/paint_module.py.
Do NOT import moodboard or space_mixie here - it causes double registration.
"""

from . import common

# Testing module is only imported when explicitly requested
# to avoid import errors during addon startup
TESTING_MODULE_AVAILABLE = False
