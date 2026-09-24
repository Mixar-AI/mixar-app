# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The agent's asset picker: which question is one, and what it offers.

When the agent searches the user's trained asset library and finds several
close matches, it pauses with a ``choice`` question whose buttons carry asset
identity (``asset_name`` / ``library`` / ``blend_file`` / ``asset_type`` /
``score``). While that question is pending the island's Agent tab stops
drawing the transcript and shows ONLY those picks, as a Library-style grid
(``space_agent_bubble/agent_ui_asset_picker.cc``). Answering it — a pick,
"Model from scratch", Cancel, or a typed reply — ends the pause and the chat
comes back on its own; nothing here has to be torn down.

The rule is DERIVED from chat state, never stored, so it cannot go stale:

* the session is ``AWAITING_INPUT``;
* the newest AGENT bubble carrying an ``input_type`` asks a ``choice``;
* that bubble still has action items with an ``asset_name``.

The C++ reader (``space_mixie_chat/mixie_chat_asset_picker.cc``) implements
the same three checks; ``tests/test_agent_asset_picker.py`` pins the pair.
The picker shows at most :data:`MAX_ASSET_PICKS` — the backend's top five.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

#: The top five: the backend never offers more (``user_input.MAX_ASSET_OPTIONS``)
#: and the picker grid never shows more. Mirrors ``MIXIE_ASSET_PICKER_MAX``.
MAX_ASSET_PICKS = 5

#: WindowManager string holding the selected pick's action VALUE. Empty or
#: stale means "the first pick" (the best match). Read by the C++ pane.
SELECTED_PROP = "mixie_chat_asset_pick_selected"

#: Values of the non-asset answers the backend appends to every picker.
CANCEL_VALUE = "abort"


@dataclass
class AssetPick:
    label: str
    value: str
    asset_name: str
    library: str
    asset_type: str
    image: str
    score: float  # -1 when the backend did not send one
    #: Library-relative .blend path — what a viewport drop appends from.
    blend_file: str = ""


@dataclass
class AssetPicker:
    bubble_id: str
    question: str
    picks: list[AssetPick] = field(default_factory=list)
    #: The "Model from scratch" answer (the one plain, non-danger button).
    scratch_value: str = ""
    scratch_label: str = ""
    #: Cancel ("abort") when the backend offered it.
    cancel_value: str = ""


def is_asset_action(action: Any) -> bool:
    return bool(getattr(action, "asset_name", ""))


def is_picker_bubble(bubble: Any) -> bool:
    """A ``choice`` question whose buttons carry library assets."""
    return (getattr(bubble, "input_type", "") == "choice"
            and any(is_asset_action(a) for a in getattr(bubble, "action_items", ())))


def _question_text(bubble: Any) -> str:
    return (getattr(bubble, "content", "") or getattr(bubble, "text", "") or "").strip()


def picker_from_bubble(bubble: Any) -> Optional[AssetPicker]:
    """The picker a bubble offers, or None when it is not an asset question."""
    if not is_picker_bubble(bubble):
        return None
    picker = AssetPicker(bubble_id=getattr(bubble, "bubble_id", "") or "",
                         question=_question_text(bubble))
    for action in bubble.action_items:
        value = getattr(action, "value", "") or ""
        if is_asset_action(action):
            if len(picker.picks) < MAX_ASSET_PICKS:
                picker.picks.append(AssetPick(
                    label=action.label or action.asset_name,
                    value=value,
                    asset_name=action.asset_name,
                    library=getattr(action, "library", "") or "",
                    asset_type=getattr(action, "asset_type", "") or "",
                    image=getattr(action, "image", "") or "",
                    score=float(getattr(action, "score", -1.0)),
                    blend_file=getattr(action, "blend_file", "") or "",
                ))
        elif getattr(action, "style", "") == "DANGER" or value == CANCEL_VALUE:
            picker.cancel_value = picker.cancel_value or value
        elif not picker.scratch_value and value:
            picker.scratch_value = value
            picker.scratch_label = action.label or value
    return picker


def live_asset_picker(scene: Any) -> Optional[AssetPicker]:
    """The pending asset question the island is showing, or None."""
    if scene is None or getattr(scene, "mixie_chat_state", "") != "AWAITING_INPUT":
        return None
    try:
        messages = list(scene.mixie_chat_messages)
    except Exception:  # noqa: BLE001 — no chat on this scene
        return None
    for bubble in reversed(messages):
        if getattr(bubble, "sender", "") != "AGENT" or not getattr(bubble, "input_type", ""):
            continue
        # The newest pending question decides; an older picker is answered.
        return picker_from_bubble(bubble)
    return None


def cap_asset_actions(actions: list) -> list:
    """Keep every plain button and the first :data:`MAX_ASSET_PICKS` asset ones."""
    kept, assets = [], 0
    for action in actions or []:
        if isinstance(action, dict) and action.get("asset_name"):
            assets += 1
            if assets > MAX_ASSET_PICKS:
                continue
        kept.append(action)
    return kept


#: The typed reply a viewport drop answers the question with: the user placed
#: the pick themselves, so the agent must use it as it is, not append it again.
DROP_REPLY = ("I placed '{asset}' from my library ({library}) into the scene myself, "
              "where I dropped it. Use it as it is, do not append it again, and continue.")


def drop_reply(pick: AssetPick) -> str:
    return DROP_REPLY.format(asset=pick.asset_name, library=pick.library or "asset library")


def ground_point(origin, direction, z: float = 0.0):
    """Where the ray from ``origin`` along ``direction`` meets the horizontal
    plane at ``z``, as an (x, y, z) tuple — None when it never does (parallel
    to it, or behind the origin). The viewport drop's fallback when nothing
    in the scene is under the cursor."""
    ox, oy, oz = origin
    dx, dy, dz = direction
    if abs(dz) < 1e-9:
        return None
    t = (z - oz) / dz
    if t <= 0.0:
        return None
    return (ox + dx * t, oy + dy * t, z)


def _tabs_locked(wm: Any) -> bool:
    """Sketch and Voice lock the island's tab strip (agent_bubble doc)."""
    return bool(getattr(wm, "mixar_mark_armed", False)
                or getattr(wm, "mixie_chat_voice_listening", False))


def present(bubble: Any) -> None:
    """A new asset question arrived: start on the best match and bring the
    Agent tab forward so the picker is what the island shows. Best-effort —
    a failure only means the user switches tab themselves."""
    try:
        import bpy
        wm = bpy.context.window_manager
    except Exception:  # noqa: BLE001 — headless / no window manager
        return
    if wm is None or not is_picker_bubble(bubble):
        return
    try:
        if hasattr(wm, SELECTED_PROP):
            setattr(wm, SELECTED_PROP, "")
        if getattr(wm, "mixar_bubble_tab", "AGENT") != "AGENT" and not _tabs_locked(wm):
            wm.mixar_bubble_tab = "AGENT"
    except Exception:  # noqa: BLE001 — never break slot application over UI state
        pass
