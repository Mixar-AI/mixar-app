# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Onboarding Step Table

A single declarative table for the info-driven flow:

    WELCOME → INFO_MOODBOARD → INFO_IMAGEGEN → INFO_IMAGE_TO_3D
            → INFO_RETOPOLOGY → INFO_MIXIE_CHAT
            → INFO_ENGINE_MODE → COMPLETION → DONE

Every step is purely informational — the user clicks Next on the
card to advance. The Engine Mode step paints a highlight around
the topbar menu item but doesn't require the user to click it;
that's just a "FYI, this is where the full toolkit lives" pointer.
"""

from dataclasses import dataclass
from typing import Optional

from mixar.modules.onboarding.constants import (
    CATEGORY_IMAGE_GEN,
    CATEGORY_IMAGE_TO_3D,
    CATEGORY_RETOPOLOGY,
    INFO_ENGINE_MODE_BODY_1,
    INFO_ENGINE_MODE_BODY_2,
    INFO_ENGINE_MODE_BODY_3,
    INFO_ENGINE_MODE_LABEL,
    INFO_IMAGE_TO_3D_BODY_1,
    INFO_IMAGE_TO_3D_BODY_2,
    INFO_IMAGE_TO_3D_LABEL,
    INFO_IMAGEGEN_BODY_1,
    INFO_IMAGEGEN_BODY_2,
    INFO_IMAGEGEN_LABEL,
    INFO_MIXIE_CHAT_BODY_1,
    INFO_MIXIE_CHAT_BODY_2,
    INFO_MIXIE_CHAT_BODY_3,
    INFO_MIXIE_CHAT_BODY_4,
    INFO_MIXIE_CHAT_LABEL,
    INFO_MOODBOARD_BODY_1,
    INFO_MOODBOARD_BODY_2,
    INFO_MOODBOARD_LABEL,
    INFO_RETOPOLOGY_BODY_1,
    INFO_RETOPOLOGY_BODY_2,
    INFO_RETOPOLOGY_LABEL,
    OP_COMPLETION,
    OP_STEP_INFO_ENGINE_MODE,
    OP_STEP_INFO_IMAGE_TO_3D,
    OP_STEP_INFO_IMAGEGEN,
    OP_STEP_INFO_MIXIE_CHAT,
    OP_STEP_INFO_MOODBOARD,
    OP_STEP_INFO_RETOPOLOGY,
    OP_WELCOME,
    STEP_COMPLETION,
    STEP_DONE,
    STEP_INFO_ENGINE_MODE,
    STEP_INFO_IMAGE_TO_3D,
    STEP_INFO_IMAGEGEN,
    STEP_INFO_MIXIE_CHAT,
    STEP_INFO_MOODBOARD,
    STEP_INFO_RETOPOLOGY,
    STEP_WELCOME,
    TOTAL_INFO_STEPS,
)

# Step kinds.
KIND_MODAL = "modal"
KIND_TERMINAL = "terminal"


@dataclass(frozen=True)
class StepDef:
    """One row of the info-driven onboarding flow."""
    id: str
    kind: str
    progress: tuple = (0, 0)
    label: str = ""
    body_lines: tuple = ()
    category: Optional[str] = None  # sidebar tab to auto-switch to
    continue_step: str = STEP_DONE
    skip_step: str = STEP_DONE
    invoke_op: str = ""


_STEPS: dict = {
    STEP_WELCOME: StepDef(
        id=STEP_WELCOME,
        kind=KIND_MODAL,
        # Copy lives in welcome_op.draw().
        continue_step=STEP_INFO_MOODBOARD,
        invoke_op=OP_WELCOME,
    ),
    STEP_INFO_MOODBOARD: StepDef(
        id=STEP_INFO_MOODBOARD,
        kind=KIND_MODAL,
        progress=(1, TOTAL_INFO_STEPS),
        label=INFO_MOODBOARD_LABEL,
        body_lines=(INFO_MOODBOARD_BODY_1, INFO_MOODBOARD_BODY_2),
        # No sidebar switch — the moodboard is the whole MIXIE space.
        category=None,
        continue_step=STEP_INFO_IMAGEGEN,
        invoke_op=OP_STEP_INFO_MOODBOARD,
    ),
    STEP_INFO_IMAGEGEN: StepDef(
        id=STEP_INFO_IMAGEGEN,
        kind=KIND_MODAL,
        progress=(2, TOTAL_INFO_STEPS),
        label=INFO_IMAGEGEN_LABEL,
        body_lines=(INFO_IMAGEGEN_BODY_1, INFO_IMAGEGEN_BODY_2),
        category=CATEGORY_IMAGE_GEN,
        continue_step=STEP_INFO_IMAGE_TO_3D,
        invoke_op=OP_STEP_INFO_IMAGEGEN,
    ),
    STEP_INFO_IMAGE_TO_3D: StepDef(
        id=STEP_INFO_IMAGE_TO_3D,
        kind=KIND_MODAL,
        progress=(3, TOTAL_INFO_STEPS),
        label=INFO_IMAGE_TO_3D_LABEL,
        body_lines=(INFO_IMAGE_TO_3D_BODY_1, INFO_IMAGE_TO_3D_BODY_2),
        category=CATEGORY_IMAGE_TO_3D,
        continue_step=STEP_INFO_RETOPOLOGY,
        invoke_op=OP_STEP_INFO_IMAGE_TO_3D,
    ),
    STEP_INFO_RETOPOLOGY: StepDef(
        id=STEP_INFO_RETOPOLOGY,
        kind=KIND_MODAL,
        progress=(4, TOTAL_INFO_STEPS),
        label=INFO_RETOPOLOGY_LABEL,
        body_lines=(INFO_RETOPOLOGY_BODY_1, INFO_RETOPOLOGY_BODY_2),
        category=CATEGORY_RETOPOLOGY,
        continue_step=STEP_INFO_MIXIE_CHAT,
        invoke_op=OP_STEP_INFO_RETOPOLOGY,
    ),
    STEP_INFO_MIXIE_CHAT: StepDef(
        id=STEP_INFO_MIXIE_CHAT,
        kind=KIND_MODAL,
        progress=(5, TOTAL_INFO_STEPS),
        label=INFO_MIXIE_CHAT_LABEL,
        body_lines=(
            INFO_MIXIE_CHAT_BODY_1,
            INFO_MIXIE_CHAT_BODY_2,
            INFO_MIXIE_CHAT_BODY_3,
            INFO_MIXIE_CHAT_BODY_4,
        ),
        # No sidebar — the chat is its own space (MIXIE_CHAT).
        category=None,
        continue_step=STEP_INFO_ENGINE_MODE,
        invoke_op=OP_STEP_INFO_MIXIE_CHAT,
    ),
    STEP_INFO_ENGINE_MODE: StepDef(
        id=STEP_INFO_ENGINE_MODE,
        kind=KIND_MODAL,
        progress=(6, TOTAL_INFO_STEPS),
        label=INFO_ENGINE_MODE_LABEL,
        body_lines=(
            INFO_ENGINE_MODE_BODY_1,
            INFO_ENGINE_MODE_BODY_2,
            INFO_ENGINE_MODE_BODY_3,
        ),
        category=None,
        continue_step=STEP_COMPLETION,
        invoke_op=OP_STEP_INFO_ENGINE_MODE,
    ),
    STEP_COMPLETION: StepDef(
        id=STEP_COMPLETION,
        kind=KIND_MODAL,
        # Copy lives in completion_ops.draw().
        continue_step=STEP_DONE,
        invoke_op=OP_COMPLETION,
    ),
    STEP_DONE: StepDef(
        id=STEP_DONE,
        kind=KIND_TERMINAL,
        continue_step=STEP_DONE,
    ),
}


def get_step(step_id: str) -> Optional[StepDef]:
    """Return the StepDef for ``step_id`` or None if unknown."""
    return _STEPS.get(step_id)


def all_step_ids() -> tuple:
    """All registered step IDs in declaration order."""
    return tuple(_STEPS.keys())
