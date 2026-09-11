# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Shared card-dialog width is the existing 640px gallery/BYOK recipe."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONSTANTS = ROOT / "src/scripts/mixar/modules/common/ui/constants.py"
GALLERY = ROOT / "src/scripts/mixar/modules/common/ui/operators/ui_gallery_ops.py"
BYOK = ROOT / "src/scripts/mixar/modules/byok/ui/operators/byok_ops.py"
SETTINGS = (
    ROOT
    / "src/scripts/mixar/modules/agent_bubble/ui/operators/pane_settings_ops.py"
)
PROFILE = ROOT / "src/scripts/mixar/modules/space_mixie_chat/ui/topbar.py"


def test_card_dialogs_use_named_640_width():
    from mixar.modules.common.ui.constants import CARD_DIALOG_WIDTH

    constants = CONSTANTS.read_text(encoding="utf-8")
    gallery = GALLERY.read_text(encoding="utf-8")
    byok = BYOK.read_text(encoding="utf-8")
    settings = SETTINGS.read_text(encoding="utf-8")
    profile = PROFILE.read_text(encoding="utf-8")
    assert CARD_DIALOG_WIDTH == 640
    assert "CARD_DIALOG_WIDTH = 640" in constants
    assert "width=CARD_DIALOG_WIDTH" in gallery
    assert "width=CARD_DIALOG_WIDTH" in byok
    assert "width=640" not in gallery
    assert "width=640" not in byok
    # Single-consumer frames stay local.
    assert "width=460" in settings
    assert "CARD_DIALOG_WIDTH" not in settings
    assert "bl_ui_units_x = 15" in profile
    assert "CARD_DIALOG_WIDTH" not in profile
