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
    PLUGIN_IMPORT_BODY_FOUND,
    PLUGIN_IMPORT_BODY_HINT,
    PLUGIN_IMPORT_BODY_UNKNOWN_1,
    PLUGIN_IMPORT_BODY_UNKNOWN_2,
    PLUGIN_IMPORT_CONFIRM_LABEL,
    PLUGIN_IMPORT_DECLINE_LABEL,
    PLUGIN_IMPORT_DONE_BODY_MANAGE,
    PLUGIN_IMPORT_DONE_BODY_NOTHING,
    PLUGIN_IMPORT_DONE_BODY_OK,
    PLUGIN_IMPORT_DONE_BODY_PROBLEM,
    PLUGIN_IMPORT_DONE_TITLE,
    PLUGIN_IMPORT_LABEL,
    PLUGIN_IMPORT_NONE_BODY_1,
    PLUGIN_IMPORT_NONE_BODY_2,
    PLUGIN_IMPORT_NONE_TITLE,
    PLUGIN_IMPORT_OUTCOME_CONFIRM_LABEL,
    STEP_COMPLETION,
    STEP_INFO_ENGINE_MODE,
    STEP_INFO_IMAGE_TO_3D,
    STEP_INFO_IMAGEGEN,
    STEP_INFO_MIXIE_CHAT,
    STEP_INFO_MOODBOARD,
    STEP_INFO_RETOPOLOGY,
    STEP_PLUGIN_IMPORT,
    STEP_PLUGIN_IMPORT_DONE,
    STEP_PLUGIN_IMPORT_NONE,
    STEP_WELCOME,
    TOTAL_INFO_STEPS,
    TOUR_DIALOG_CONFIRM_NEXT,
    WELCOME_CONFIRM_LABEL,
    WELCOME_HEADING,
    WELCOME_SUBHEADING,
    WELCOME_TITLE,
)
from mixar.modules.onboarding.core.steps import get_step, numbered_progress

_SKIP_LABEL_DEFAULT = "Skip tour"
_SKIP_LABEL_WELCOME = "I'll figure it out myself"
_SKIP_LABEL_COMPLETION = ""  # no skip link on the completion screen


# ---------------------------------------------------------------------------
# Plugin-import step (7) and its two outcome cards.
#
# Copy is built at config time rather than declared in the step table:
# neither the plugin count nor the import result is known until the
# scan/import actually runs.
# ---------------------------------------------------------------------------


def _plural_plugins(count: int) -> str:
    return "1 plugin" if count == 1 else f"{count} plugins"


def _plugin_import_body() -> tuple:
    """Body copy for the offer card, naming the count when we have it."""
    from mixar.modules.onboarding.core import plugin_import_bridge

    scan = plugin_import_bridge.scan()
    if not scan.found:
        # No scan hit — don't claim a count. The Import button still
        # works and lands the user on the "nothing found" card.
        return (PLUGIN_IMPORT_BODY_UNKNOWN_1, PLUGIN_IMPORT_BODY_UNKNOWN_2)

    return (
        PLUGIN_IMPORT_BODY_FOUND.format(
            count=_plural_plugins(scan.count), version=scan.version,
        ),
        PLUGIN_IMPORT_BODY_HINT,
    )


def _import_done_body() -> tuple:
    """Body copy for the result card, from the import summary."""
    from mixar.modules.onboarding.core import plugin_import_bridge

    result = plugin_import_bridge.last_import_result()

    if result.did_nothing:
        lines = [PLUGIN_IMPORT_DONE_BODY_NOTHING]
    else:
        lines = [
            PLUGIN_IMPORT_DONE_BODY_OK.format(
                imported=result.imported, enabled=result.enabled,
            )
        ]

    problem_count = result.failed + result.enable_failed
    if problem_count:
        lines.append(
            PLUGIN_IMPORT_DONE_BODY_PROBLEM.format(failed=problem_count)
        )

    lines.append(PLUGIN_IMPORT_DONE_BODY_MANAGE)
    return tuple(lines)


def _plugin_import_config() -> dict:
    step = get_step(STEP_PLUGIN_IMPORT)
    dots_current, dots_total = numbered_progress(STEP_PLUGIN_IMPORT)
    return {
        "host_area": "VIEW_3D",
        "position": CARD_POS_TOP_RIGHT,
        "title": PLUGIN_IMPORT_LABEL,
        "body_lines": _plugin_import_body(),
        "primary_label": PLUGIN_IMPORT_CONFIRM_LABEL,
        "primary_action": step.primary_action if step else "",
        "alt_label": PLUGIN_IMPORT_DECLINE_LABEL,
        "alt_step": step.alt_step if step else STEP_COMPLETION,
        "alt_visible": True,
        "skip_label": _SKIP_LABEL_DEFAULT,
        "skip_visible": False,
        "scale": CARD_SCALE_DEFAULT,
        "icon_id": ICON_ENGINE,
        "dots_current": dots_current,
        "dots_total": dots_total,
        "back_visible": True,
    }


def _plugin_outcome_config(step_id, icon_id, body_lines, title,
                           back_visible) -> dict:
    return {
        "host_area": "VIEW_3D",
        "position": CARD_POS_TOP_RIGHT,
        "title": title,
        "body_lines": body_lines,
        "primary_label": PLUGIN_IMPORT_OUTCOME_CONFIRM_LABEL,
        "skip_label": _SKIP_LABEL_DEFAULT,
        "skip_visible": False,
        "scale": CARD_SCALE_DEFAULT,
        "icon_id": icon_id,
        # Outcome cards are a detour off step 7, not steps of their own.
        "dots_current": 0,
        "dots_total": 0,
        "back_visible": back_visible,
    }


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
            "back_visible": False,  # first step — nowhere to go back
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
            "back_visible": True,  # let users step back to review
        }

    if step_id == STEP_PLUGIN_IMPORT:
        return _plugin_import_config()

    if step_id == STEP_PLUGIN_IMPORT_NONE:
        return _plugin_outcome_config(
            STEP_PLUGIN_IMPORT_NONE, ICON_ENGINE,
            (PLUGIN_IMPORT_NONE_BODY_1, PLUGIN_IMPORT_NONE_BODY_2),
            PLUGIN_IMPORT_NONE_TITLE,
            # No Back: the offer card that led here is gated on finding
            # plugins, and this card only appears when that check has
            # just disagreed — there is nothing coherent to go back to.
            back_visible=False,
        )

    if step_id == STEP_PLUGIN_IMPORT_DONE:
        return _plugin_outcome_config(
            STEP_PLUGIN_IMPORT_DONE, ICON_CHECKMARK,
            _import_done_body(),
            PLUGIN_IMPORT_DONE_TITLE,
            # The import already ran — going back would re-offer it.
            back_visible=False,
        )

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

    # Counted from the steps actually being shown this run — an optional
    # step that dropped out must not leave a gap in the numbering.
    current, total = numbered_progress(step_id)
    if not total:
        current = step.progress[0] if step.progress else 0
        total = (
            step.progress[1]
            if step.progress and step.progress[1]
            else TOTAL_INFO_STEPS
        )

    return {
        "host_area": host_area,
        "position": position,
        "title": step.label,
        "body_lines": step.body_lines,
        "primary_label": TOUR_DIALOG_CONFIRM_NEXT,
        "skip_label": _SKIP_LABEL_DEFAULT,
        # Skip link removed from the row to declutter — skipping is
        # handled by clicking outside the card or pressing Esc (the
        # on-screen hint communicates this). Back is the only secondary
        # control since no other gesture covers going back a step.
        "skip_visible": False,
        "scale": scale,
        "icon_id": info_icon.get(step_id, ICON_WELCOME),
        "dots_current": current,
        "dots_total": total,
        "back_visible": True,
    }
