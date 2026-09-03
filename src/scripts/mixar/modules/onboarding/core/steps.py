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
from typing import Callable, Optional

from mixar.config.logging_config import get_logger

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
    PLUGIN_IMPORT_DECLINE_LABEL,
    PLUGIN_IMPORT_DONE_TITLE,
    PLUGIN_IMPORT_LABEL,
    PLUGIN_IMPORT_NONE_BODY_1,
    PLUGIN_IMPORT_NONE_BODY_2,
    PLUGIN_IMPORT_NONE_TITLE,
    STEP_COMPLETION,
    STEP_DONE,
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
)

logger = get_logger(__name__)

# Step kinds.
KIND_MODAL = "modal"
KIND_TERMINAL = "terminal"

# Named primary-button side effects (StepDef.primary_action). The action
# runs on the main thread from the card modal's deferred timer and is
# responsible for transitioning to whichever step its outcome implies.
ACTION_IMPORT_PLUGINS = "import_plugins"


def _has_plugins_to_import() -> bool:
    """Only offer the import card when there is actually something to
    import — no Blender installed, or none of its versions carrying user
    plugins, means the card would waste a step on a dead end.

    Also False once the import has actually run. STEP_COMPLETION comes
    back here, and ``_resolve_available`` walks the predicate in BOTH
    directions, so without this Back from Completion lands on the offer
    card again and re-offers an import the user already performed — the
    very thing STEP_PLUGIN_IMPORT_DONE's empty ``back_step`` prevents on
    the way forward. Declining is not "ran": that path keeps its Back.
    """
    try:
        from mixar.modules.onboarding.core import plugin_import_bridge
        if plugin_import_bridge.import_ran():
            return False
        return plugin_import_bridge.scan().found
    except Exception:  # noqa: BLE001 — never break the tour over this
        return False


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
    # Step to return to when the user clicks Back. Empty string means
    # "no previous step" (the welcome card, which hides its Back link).
    back_step: str = ""
    invoke_op: str = ""
    # Optional second button, left of the primary one. When set, the card
    # draws ``alt_label`` and clicking it transitions straight to
    # ``alt_step`` — the one place the flow branches rather than running
    # straight down ``continue_step``.
    alt_label: str = ""
    alt_step: str = ""
    # Optional named side effect the primary button runs INSTEAD of a
    # plain advance(). The action decides which step comes next, so a
    # card whose outcome isn't known until the button is pressed (the
    # plugin import) doesn't need a second state machine.
    primary_action: str = ""
    # Optional predicate deciding whether this step is worth showing at
    # all. Returning False makes the flow step straight over it in BOTH
    # directions (see state._resolve_available). Steps without one are
    # always shown.
    available: Optional[Callable[[], bool]] = None


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
        back_step=STEP_WELCOME,
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
        back_step=STEP_INFO_MOODBOARD,
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
        back_step=STEP_INFO_IMAGEGEN,
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
        back_step=STEP_INFO_IMAGE_TO_3D,
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
        ),
        # No sidebar — the chat is its own space (MIXIE_CHAT).
        category=None,
        continue_step=STEP_INFO_ENGINE_MODE,
        back_step=STEP_INFO_RETOPOLOGY,
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
        continue_step=STEP_PLUGIN_IMPORT,
        back_step=STEP_INFO_MIXIE_CHAT,
        invoke_op=OP_STEP_INFO_ENGINE_MODE,
    ),
    STEP_PLUGIN_IMPORT: StepDef(
        id=STEP_PLUGIN_IMPORT,
        kind=KIND_MODAL,
        progress=(7, TOTAL_INFO_STEPS),
        label=PLUGIN_IMPORT_LABEL,
        # Body copy is built in card_config from the scan result.
        body_lines=(),
        category=None,
        # Unused: primary_action decides the next step (imported vs
        # nothing-found). Kept pointing at COMPLETION so a fallback
        # advance() can never strand the user mid-tour.
        continue_step=STEP_COMPLETION,
        back_step=STEP_INFO_ENGINE_MODE,
        alt_label=PLUGIN_IMPORT_DECLINE_LABEL,
        alt_step=STEP_COMPLETION,
        primary_action=ACTION_IMPORT_PLUGINS,
        available=_has_plugins_to_import,
    ),
    # Reached ONLY when the re-scan on the Import button comes back
    # empty — i.e. Blender was uninstalled, or its config tree became
    # unreadable, between the card being shown and the click. The
    # ``available`` gate above means the offer card never appears when
    # we already know there is nothing, so this is a race fallback, not
    # a normal branch. It must stay: the Import handler needs somewhere
    # to land when its own re-scan disagrees with the earlier one.
    STEP_PLUGIN_IMPORT_NONE: StepDef(
        id=STEP_PLUGIN_IMPORT_NONE,
        kind=KIND_MODAL,
        label=PLUGIN_IMPORT_NONE_TITLE,
        body_lines=(PLUGIN_IMPORT_NONE_BODY_1, PLUGIN_IMPORT_NONE_BODY_2),
        category=None,
        continue_step=STEP_COMPLETION,
        back_step="",
    ),
    STEP_PLUGIN_IMPORT_DONE: StepDef(
        id=STEP_PLUGIN_IMPORT_DONE,
        kind=KIND_MODAL,
        label=PLUGIN_IMPORT_DONE_TITLE,
        # Body copy is built in card_config from the import summary.
        body_lines=(),
        category=None,
        continue_step=STEP_COMPLETION,
        # No Back: the import already happened, so stepping back to an
        # offer the user has answered would just invite a double import.
        back_step="",
    ),
    STEP_COMPLETION: StepDef(
        id=STEP_COMPLETION,
        kind=KIND_MODAL,
        # Copy lives in completion_ops.draw().
        continue_step=STEP_DONE,
        back_step=STEP_PLUGIN_IMPORT,
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


def is_available(step_id: str) -> bool:
    """False when a step declares an ``available`` predicate that says
    it isn't worth showing. Unknown steps are 'available' so a typo
    surfaces as a visible broken card rather than a silently skipped one.
    """
    step = get_step(step_id)
    if step is None or step.available is None:
        return True
    try:
        return bool(step.available())
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Onboarding: availability check failed for %s: %s", step_id, exc,
        )
        return False


def numbered_progress(step_id: str) -> tuple:
    """Return ``(current, total)`` for the step-dot row, counting only
    steps that are actually being shown this run.

    The static ``progress`` tuples on the table can't be used directly:
    a skipped step would leave a gap ("STEP 7 OF 7" on a six-card tour).
    Walking the live chain keeps the dots honest however many optional
    steps drop out.
    """
    shown = _numbered_chain()
    if step_id not in shown:
        return (0, 0)
    return (shown.index(step_id) + 1, len(shown))


def _numbered_chain() -> list:
    """Ordered ids of the numbered steps available this run.

    Walks ``continue_step`` from the welcome card rather than the dict's
    declaration order, so the chain is the flow the user will actually
    take. Guarded against a cycle in the table.
    """
    chain = []
    seen = set()
    current = STEP_WELCOME
    while current and current not in seen:
        seen.add(current)
        step = _STEPS.get(current)
        if step is None:
            break
        if step.progress and step.progress[0] and is_available(current):
            chain.append(current)
        current = step.continue_step
    return chain
