# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — video-narrated, clickable onboarding.

``beats`` (the script) and ``runner`` (the state machine) are pure Python;
``anchors``, ``actions``, ``clock``, ``video`` and ``session`` talk to the
running app and are only imported from the modal operator.
"""

from . import config


def is_available() -> bool:
    """True when the tour can run: a video asset is bundled. Audio is not
    required (the clock falls back to a silent wall clock)."""
    return bool(config.video_path())
