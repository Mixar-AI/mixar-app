# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Per-step card configuration.

Maps each ``step_id`` to the rendering parameters the card modal
operator needs: host area, anchor position, scale, title/body copy,
icon, progress dots, and skip-link label.
"""

from mixar.modules.onboarding.constants import (
    CARD_POS_AREA_CENTER,
    CARD_POS_NEAR_BUBBLE,
    CARD_POS_SIDEBAR_ADJACENT,
    CARD_POS_TOP_LEFT,
    CARD_POS_TOP_RIGHT,
    CARD_SCALE_DEFAULT,
    CARD_SCALE_WELCOME,
    COMPLETION_CONFIRM_LABEL,
    COMPLETION_SUBTITLE,
    COMPLETION_TITLE,
    ICON_CHAT,
    ICON_CHECKMARK,
    ICON_ENGINE,
    ICON_IMAGE_TO_3D,
    ICON_IMAGEGEN,
    ICON_MOODBOARD,
    ICON_RETOPOLOGY,
    ICON_WELCOME,
    STEP_COMPLETION,
    STEP_INFO_ENGINE_MODE,
    STEP_INFO_IMAGE_TO_3D,
    STEP_INFO_IMAGEGEN,
    STEP_INFO_MIXIE_CHAT,
    STEP_INFO_MOODBOARD,
    STEP_INFO_RETOPOLOGY,
    STEP_WELCOME,
    TOTAL_INFO_STEPS,
    TOUR_DIALOG_CONFIRM_NEXT,
    WELCOME_CONFIRM_LABEL,
    WELCOME_HEADING,
    WELCOME_SUBHEADING,
    WELCOME_TITLE,
)
from mixar.modules.onboarding.core.steps import get_step

_SKIP_LABEL_DEFAULT = "Skip tour"
_SKIP_LABEL_WELCOME = "I'll figure it out myself"
_SKIP_LABEL_COMPLETION = ""  # no skip link on the completion screen


def step_card_config(step_id: str) -> dict:
    """Return all parameters needed to render this step's card."""
    info_icon = {
        STEP_INFO_MOODBOARD: ICON_MOODBOARD,
        STEP_INFO_IMAGEGEN: ICON_IMAGEGEN,
        STEP_INFO_IMAGE_TO_3D: ICON_IMAGE_TO_3D,
        STEP_INFO_RETOPOLOGY: ICON_RETOPOLOGY,
        STEP_INFO_MIXIE_CHAT: ICON_CHAT,
        STEP_INFO_ENGINE_MODE: ICON_ENGINE,
    }

    if step_id == STEP_WELCOME:
        return {
            "host_area": "MIXIE",
            "position": CARD_POS_TOP_LEFT,
            "title": WELCOME_TITLE,
            "body_lines": (WELCOME_SUBHEADING, WELCOME_HEADING),
            "primary_label": WELCOME_CONFIRM_LABEL,
            "skip_label": _SKIP_LABEL_WELCOME,
            "skip_visible": False,
            "scale": CARD_SCALE_WELCOME,
            "icon_id": ICON_WELCOME,
            "dots_current": 0,
            "dots_total": 0,
        }

    if step_id == STEP_COMPLETION:
        return {
            "host_area": "MIXIE",
            "position": CARD_POS_TOP_LEFT,
            "title": COMPLETION_TITLE,
            "body_lines": (COMPLETION_SUBTITLE,),
            "primary_label": COMPLETION_CONFIRM_LABEL,
            "skip_label": _SKIP_LABEL_COMPLETION,
            "skip_visible": False,
            "scale": CARD_SCALE_DEFAULT,
            "icon_id": ICON_CHECKMARK,
            "dots_current": 0,
            "dots_total": 0,
        }

    step = get_step(step_id)
    if step is None:
        return {}

    if step_id in (STEP_INFO_IMAGEGEN, STEP_INFO_IMAGE_TO_3D, STEP_INFO_RETOPOLOGY):
        position = CARD_POS_TOP_LEFT
        host_area = "MIXIE"
        scale = CARD_SCALE_DEFAULT
    elif step_id == STEP_INFO_MIXIE_CHAT:
        position = CARD_POS_TOP_RIGHT
        host_area = "VIEW_3D"
        scale = 0.9
    elif step_id == STEP_INFO_ENGINE_MODE:
        position = CARD_POS_TOP_RIGHT
        host_area = "VIEW_3D"
        scale = CARD_SCALE_DEFAULT
    else:
        position = CARD_POS_TOP_LEFT
        host_area = "MIXIE"
        scale = CARD_SCALE_DEFAULT

    current = step.progress[0] if step.progress else 0
    total = step.progress[1] if step.progress and step.progress[1] else TOTAL_INFO_STEPS

    return {
        "host_area": host_area,
        "position": position,
        "title": step.label,
        "body_lines": step.body_lines,
        "primary_label": TOUR_DIALOG_CONFIRM_NEXT,
        "skip_label": _SKIP_LABEL_DEFAULT,
        "skip_visible": True,
        "scale": scale,
        "icon_id": info_icon.get(step_id, ICON_WELCOME),
        "dots_current": current,
        "dots_total": total,
    }
