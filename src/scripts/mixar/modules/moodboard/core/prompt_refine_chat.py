# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Agent chat composer as a Refine / Revert slot.

The island's Refine and Revert buttons sit left of Send and run the SAME
engine and operators as the moodboard prompts (``core.prompt_refine``,
``mixie.refine_prompt`` / ``mixie.revert_prompt`` with ``chat=True``); only
the field differs. State lives on Scene RNA, like a canvas node's, because the
island is painted in C++ and has to choose between Refine, Revert and a busy
button without calling into Python. All of it is ``SKIP_SAVE``
(``space_mixie_chat/ui/properties/chat_props.py``).

The composer is the one prompt field that empties itself: every send clears
it. Two rules follow, both enforced by ``chat_props.on_chat_input_changed``,
which bumps ``mixie_chat_prompt_refine_epoch`` and drops the stash whenever
the input becomes empty (by property name, so the chat never imports this
module):

- a stash belongs to the draft it was taken from — Revert must never put an
  already-sent message back into the next one;
- a refinement still in flight when the message is sent belongs to that
  message. The slot captures the epoch it was built in and reads dead once
  it moves, so the late answer is dropped instead of refilling the empty
  composer with a rewrite of what was just sent.

The epoch, not the message count: an assistant reply streams messages in
while a refinement is out, and that must not cancel it.
"""

from __future__ import annotations

from typing import Optional

from .prompt_refine import _Slot

# The generation-target key the backend's profile table is looked up by. The
# chat is not a generation service, so this is a reserved key with its own
# profile row: agent instructions ("bevel the selected edges, then add three
# lights") must keep their imperative steps and scene references, which the
# generic generative-model default would strip as conversational framing.
# Until that row exists the backend refines through its default profile.
CHAT_REFINE_SERVICE_KEY = "agent_chat"


class ChatSlot(_Slot):
    """``scene.mixie_chat_input`` — the Agent island's composer."""

    def __init__(self, scene):
        self._scene = scene
        self._epoch = _epoch(scene)
        self.key = "chat"
        self.service_key = CHAT_REFINE_SERVICE_KEY
        self.model_slug = ""

    def read(self) -> str:
        return (getattr(self._scene, "mixie_chat_input", "") or "") if self.alive() else ""

    def write(self, text: str) -> None:
        if self.alive():
            self._scene.mixie_chat_input = text

    def stash(self, original: str) -> None:
        if not self.alive():
            return
        self._scene.mixie_chat_prompt_pre_refine = original
        self._scene.mixie_chat_prompt_refined = True

    def stashed(self) -> str:
        if not self.alive():
            return ""
        return getattr(self._scene, "mixie_chat_prompt_pre_refine", "") or ""

    def has_stash(self) -> bool:
        return self.alive() and bool(getattr(self._scene, "mixie_chat_prompt_refined", False))

    def clear_stash(self) -> None:
        if not self.alive():
            return
        self._scene.mixie_chat_prompt_pre_refine = ""
        self._scene.mixie_chat_prompt_refined = False

    def set_running(self, running: bool) -> None:
        if self.alive():
            self._scene.mixie_chat_prompt_refining = running

    def is_running(self) -> bool:
        return self.alive() and bool(getattr(self._scene, "mixie_chat_prompt_refining", False))

    def alive(self) -> bool:
        """False once the scene is gone or the draft was sent or cleared."""
        current = _epoch(self._scene)
        return current is not None and current == self._epoch


def _epoch(scene) -> Optional[int]:
    """The composer's draft generation, or None when the scene is gone."""
    try:
        return int(getattr(scene, "mixie_chat_prompt_refine_epoch", 0) or 0)
    except ReferenceError:
        # The scene was freed (file load); Blender invalidates its wrapper.
        return None


def chat_slot(scene) -> Optional[ChatSlot]:
    """The slot behind the chat composer, or None without the chat props."""
    if scene is None or not hasattr(scene, "mixie_chat_input"):
        return None
    return ChatSlot(scene)

