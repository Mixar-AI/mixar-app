# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""WindowManager mirror of the running turn's parallel agents.

The Parallel Agents panel is a custom-drawn C++ View3D region
(``view3d_agent_panel_*.cc``) and cannot reach a Python module cache, so the
task list that arrives on the chat's ``todo`` slot is projected onto RNA here
(same contract as the profile card's ``mixar_usage_*`` mirror).

**WindowManager, never Scene**: this is transient turn state. A card list
serialized into a shared ``.blend`` would carry one user's agent tasks to
whoever opens it, and would come back stale on load.

``core/cards.py`` owns the writes and is the only module that should touch
these properties.
"""

from __future__ import annotations

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import PropertyGroup

from ...constants import (
    AGENT_NAME_MAXLEN,
    AGENT_TASK_ID_MAXLEN,
    AGENT_TASK_MAXLEN,
)


class MixarAgentCard(PropertyGroup):
    """One parallel agent: the task it was given and how that task is going."""

    task_id: StringProperty(
        name="Task ID",
        description="Backend task id — the identity card updates match on",
        default="",
        maxlen=AGENT_TASK_ID_MAXLEN,
    )
    name: StringProperty(
        name="Agent Name",
        description="Display name, derived from the task the agent was assigned",
        default="",
        maxlen=AGENT_NAME_MAXLEN,
    )
    task: StringProperty(
        name="Task",
        description="Full task label as the backend streamed it",
        default="",
        maxlen=AGENT_TASK_MAXLEN,
    )
    status: EnumProperty(
        name="Status",
        description="Current status of this agent's task",
        items=[
            ('PENDING', "Pending", "Queued, not dispatched yet"),
            ('RUNNING', "Running", "Executing now"),
            ('DONE', "Done", "Finished successfully"),
            ('FAILED', "Failed", "Errored, or skipped because a dependency failed"),
        ],
        default='PENDING',
    )
    started_at: FloatProperty(
        name="Started At",
        description="Monotonic clock reading when this agent started; 0 while pending",
        default=0.0,
    )
    dismissing: BoolProperty(
        name="Dismissing",
        description=(
            "Set when the user clicks this card away. The panel plays the same "
            "slide-out a finished card gets, and the row is removed once it "
            "has left — clicking must not make a card vanish under the cursor"
        ),
        default=False,
    )
    ended_at: FloatProperty(
        name="Ended At",
        description="Monotonic clock reading when this agent settled; 0 while unsettled",
        default=0.0,
    )


#: Every property this module attaches to WindowManager, for a clean unregister.
_PROP_NAMES = (
    "mixar_agent_cards",
    "mixar_agent_cards_active",
    "mixar_agent_cards_generation",
)

classes = (MixarAgentCard,)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)

    wm = bpy.types.WindowManager
    wm.mixar_agent_cards = CollectionProperty(
        type=MixarAgentCard,
        name="Agent Cards",
        description="Parallel agents of the running turn, newest fan-out first",
        options={'SKIP_SAVE'},
    )
    wm.mixar_agent_cards_generation = IntProperty(
        name="Agent Cards Generation",
        description=(
            "Bumped every time a NEW fan-out replaces the panel's contents. "
            "The C++ panel resets its scroll position and replays the "
            "slide-in when this changes — it cannot infer 'new turn' from its "
            "own card list, which only re-syncs on a draw and so still holds "
            "the previous turn's cards while the panel is poll-hidden"
        ),
        default=0,
        min=0,
        options={'SKIP_SAVE'},
    )
    wm.mixar_agent_cards_active = IntProperty(
        name="Active Agent Cards",
        description=(
            "Cards the panel should show. Read by the region poll on every "
            "event-loop cycle, so it must stay a single property read — never "
            "a walk of the collection"
        ),
        default=0,
        min=0,
        options={'SKIP_SAVE'},
    )


def unregister() -> None:
    for name in _PROP_NAMES:
        try:
            delattr(bpy.types.WindowManager, name)
        except Exception:  # noqa: BLE001 — never registered / already gone
            pass
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:  # noqa: BLE001
            pass
