# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Where a transcript goes: resolving and writing one text target.

A target is captured when recording STARTS and carried to the end untouched.
That is the whole point of this module: the audio belongs to the field the
user was standing in when they pressed the mic, and by the time a transcript
comes back they may have clicked elsewhere, selected another node, or switched
scene. Re-reading "the focused field" at the end would paste words into
something the user never spoke into.

Targets are plain strings so they can ride an operator property and a
WindowManager mirror without a registry:

    ``chat``                     the agent chat composer (shared by the Mixie
                                 chat editor and the Agent Bubble — one
                                 property backs both)
    ``node:<node_id>``           a moodboard inference node's prompt
    ``tab:<PropsRnaIdentifier>`` a moodboard N-panel tab prompt, named by the
                                 owning PropertyGroup exactly as
                                 ``prompt_submit.PROMPT_TAB_DISPATCH`` names it

A target that no longer resolves (the node was deleted, the scene is gone) is
reported as missing and the transcript is DROPPED with a message — never
written to a neighbouring field as a consolation.
"""

from __future__ import annotations

from typing import Optional, Tuple

from mixar.config.logging_config import get_logger

from ..constants import (
    SUBMIT_MARKER,
    TARGET_CHAT,
    TARGET_NODE_PREFIX,
    TARGET_TAB_PREFIX,
)

logger = get_logger(__name__)

#: Tab PropertyGroup identifier -> the sidebar attribute holding it. The
#: dispatch table in ``moodboard/core/prompt_submit.py`` is the one list of
#: prompt-owning tabs; this maps the same identifiers to where they live, so a
#: tab that gains a prompt is added in both places or the mic simply cannot
#: address it (it is never guessed).
_TAB_ATTRIBUTES = {
    "MixieMoodboardTabImageGenProps": "tab_imagegen",
    "MixieMoodboardTabLookdevProps": "tab_lookdev",
    "MixieMoodboardTabLookdev360Props": "tab_lookdev360",
    "MixieMoodboardTabPBRGenProps": "tab_pbr_gen",
    "MixieMoodboardTabImageTo3DProps": "tab_image_to_3d",
    "MixieMoodboardTabMeshSegmentProps": "tab_mesh_segment",
    "MixieMoodboardTabVideoGenProps": "tab_video_gen",
    "MixieMoodboardTabVideoUpscaleProps": "tab_video_upscale",
    "MixieMoodboardTabWorldLabsProps": "tab_world_labs",
    "MixieMoodboardTabSceneReconProps": "tab_scene_recon",
}


def target_for_tab(owner_type: str) -> str:
    """Target string for an N-panel tab, named by its PropertyGroup."""
    return f"{TARGET_TAB_PREFIX}{owner_type}"


def target_for_node(node_id: str) -> str:
    """Target string for a moodboard inference node."""
    return f"{TARGET_NODE_PREFIX}{node_id}"


def is_valid_target(target: str) -> bool:
    """Whether this string names a shape we know how to write to.

    Shape only — it says nothing about whether the node still exists. A target
    that fails this was built wrong (a typo in a draw call), which is a bug
    rather than a user-visible state.
    """
    if target == TARGET_CHAT:
        return True
    if target.startswith(TARGET_NODE_PREFIX):
        return bool(target[len(TARGET_NODE_PREFIX):])
    if target.startswith(TARGET_TAB_PREFIX):
        return target[len(TARGET_TAB_PREFIX):] in _TAB_ATTRIBUTES
    return False


def _resolve(scene, target: str) -> Optional[Tuple[object, str]]:
    """``(owner, property_name)`` for a target, or None if it is gone."""
    if scene is None:
        return None

    if target == TARGET_CHAT:
        return (scene, "mixie_chat_input")

    if target.startswith(TARGET_NODE_PREFIX):
        node_id = target[len(TARGET_NODE_PREFIX):]
        for node in getattr(scene, "mixie_moodboard_action_nodes", []):
            if getattr(node, "node_id", "") == node_id:
                return (node, "prompt")
        return None

    if target.startswith(TARGET_TAB_PREFIX):
        attribute = _TAB_ATTRIBUTES.get(target[len(TARGET_TAB_PREFIX):])
        if not attribute:
            return None
        sidebar = getattr(scene, "mixie_moodboard_sidebar", None)
        tab = getattr(sidebar, attribute, None) if sidebar is not None else None
        return (tab, "prompt") if tab is not None else None

    return None


def target_exists(scene, target: str) -> bool:
    return _resolve(scene, target) is not None


def read_target(scene, target: str) -> str:
    resolved = _resolve(scene, target)
    if resolved is None:
        return ""
    owner, attribute = resolved
    return str(getattr(owner, attribute, "") or "")


def insert_transcript(scene, target: str, transcript: str) -> bool:
    """Append a transcript to its target field. Returns False if it is gone.

    APPEND, never replace: the user may have typed half a sentence before
    dictating the rest, and throwing that away to make room for speech would
    be the surprise this feature least needs. A single space joins them when
    the existing text does not already end in whitespace.

    The submit marker is stripped first. The chat composer's update callback
    reads that character as "Enter was pressed" and sends the message, so a
    transcript carrying one would fire the message mid-insert — the same trap
    the paste path documents.
    """
    text = (transcript or "").replace(SUBMIT_MARKER, "").strip()
    if not text:
        return True

    resolved = _resolve(scene, target)
    if resolved is None:
        logger.info(f"[Voice] target {target!r} is gone; dropping the transcript")
        return False

    owner, attribute = resolved
    existing = str(getattr(owner, attribute, "") or "")
    if existing and not existing[-1].isspace():
        combined = f"{existing} {text}"
    else:
        combined = f"{existing}{text}"

    try:
        setattr(owner, attribute, combined)
    except Exception:
        # A maxlen overflow or a property that vanished between the resolve
        # and the write. Report it rather than half-writing.
        logger.exception(f"[Voice] could not write the transcript to {target!r}")
        return False
    return True
