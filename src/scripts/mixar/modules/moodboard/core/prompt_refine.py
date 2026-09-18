# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Refine / Revert for every generation prompt field.

The user types a prompt, presses **Refine**, and the backend rewrites it for
the model that prompt is destined for. The rewritten text replaces what they
typed and a **Revert** button joins Refine, which puts their own words back —
Refine stays, so a rewrite that did not land can simply be run again.

Two rules shape everything here:

- **Nothing the user wrote is ever lost.** The original is stashed BEFORE the
  field is overwritten, and only ever cleared by an explicit Revert or by the
  user editing the field themselves. Only the FIRST refinement stashes: a
  second pass rewrites the refinement, and Revert must still return the
  user's own words rather than stepping back one machine-written draft. A
  failed refinement leaves the field exactly as it was, and the stash
  outlives a reconnect because it is local (the backend keeps no per-user
  refinement state).
- **Refine targets the model the prompt will actually be sent to.** Service
  key and model slug are resolved through the same catalog helpers the tab's
  own Mode/Model dropdowns use, so Refine can never refine for one model
  while Generate submits to another. See :mod:`prompt_refine_targets`.

Two kinds of field, one engine. A sidebar tab's stash lives in this module
(transient UI state, nothing to serialize); a canvas node's lives on the node
itself, because the node card is drawn in C++ and the draw pass has to know
whether to paint Refine or Revert without calling into Python.

Threading: the request goes out on the shared async API queue, whose
callbacks are delivered on Blender's main thread — so the apply path writes
RNA directly and no marshalling is needed.
"""

from __future__ import annotations

from typing import Callable, Optional

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# Sidebar stashes and in-flight markers, keyed by OWNING SCENE plus the owner
# PropertyGroup's RNA identifier (one prompt per tab per scene). Deliberately
# module state and not RNA: it is per-session UI affordance, and a pre-refine
# prompt has no business in a saved .blend. The scene is part of the key
# because the sidebar props are registered per Scene: keyed by tab alone,
# Scene B's Revert would offer — and write — Scene A's stashed prompt.
_sidebar_stash: dict[str, str] = {}
_sidebar_running: set[str] = set()


def _sidebar_key(owner, owner_type: str) -> str:
    """``<scene>:<owner_type>`` — the scene by ``session_uid`` (stable across
    a rename within the session, never reused), falling back to its name."""
    scene = getattr(owner, "id_data", None)
    uid = getattr(scene, "session_uid", None)
    scene_id = str(uid) if isinstance(uid, int) and uid else str(getattr(scene, "name", "") or "")
    return f"{scene_id}:{owner_type}"


# ---------------------------------------------------------------------------
# Slots — the two kinds of prompt field, behind one interface
# ---------------------------------------------------------------------------

class _Slot:
    """One prompt field: read it, write it, remember what was there."""

    key = ""
    service_key = ""
    model_slug = ""

    def read(self) -> str:
        raise NotImplementedError

    def write(self, text: str) -> None:
        raise NotImplementedError

    def stash(self, original: str) -> None:
        raise NotImplementedError

    def stashed(self) -> str:
        raise NotImplementedError

    def has_stash(self) -> bool:
        """True once a refinement has something to revert TO.

        Distinct from a non-empty ``stashed()``: reverting to an empty
        prompt is legitimate, and the two must not be confused.
        """
        raise NotImplementedError

    def clear_stash(self) -> None:
        raise NotImplementedError

    def set_running(self, running: bool) -> None:
        raise NotImplementedError

    def is_running(self) -> bool:
        raise NotImplementedError

    def alive(self) -> bool:
        """False once the field is gone (scene closed, node deleted)."""
        return True


class SidebarSlot(_Slot):
    """A moodboard N-panel tab prompt."""

    def __init__(self, owner, owner_type: str, service_key: str, model_slug: str):
        self._owner = owner
        self.key = _sidebar_key(owner, owner_type)
        self.service_key = service_key
        self.model_slug = model_slug

    def read(self) -> str:
        return getattr(self._owner, "prompt", "") or ""

    def write(self, text: str) -> None:
        self._owner.prompt = text

    def stash(self, original: str) -> None:
        _sidebar_stash[self.key] = original

    def stashed(self) -> str:
        return _sidebar_stash.get(self.key, "")

    def has_stash(self) -> bool:
        return self.key in _sidebar_stash

    def clear_stash(self) -> None:
        _sidebar_stash.pop(self.key, None)

    def set_running(self, running: bool) -> None:
        if running:
            _sidebar_running.add(self.key)
        else:
            _sidebar_running.discard(self.key)

    def is_running(self) -> bool:
        return self.key in _sidebar_running

    def alive(self) -> bool:
        try:
            return self._owner is not None and bool(self._owner.bl_rna)
        except (ReferenceError, AttributeError):
            return False


class NodeSlot(_Slot):
    """An inference-graph node's in-tile prompt.

    State lives on the node's own RNA rather than in this module because the
    card is painted in C++: the draw pass reads ``prompt_refined`` and
    ``prompt_refining`` to choose between Refine, Revert and a disabled
    button, and it cannot consult a Python dict to do it.

    The slot holds the node's ID STRING, never the node, and re-resolves it
    on every access. A refine is a live round trip, and a collection
    element's RNA pointer dangles as soon as the collection is edited --
    the node deleted, the board cleared, another file opened. ``bl_rna``
    cannot catch that: it answers off the cached type without ever
    dereferencing the element, so a liveness check through the stored
    pointer reads True and the write that follows lands on freed memory.
    Same rule as every other async path here (``voice/core/targets.py``,
    ``director/core/render_target.py``): re-resolve by id.
    """

    def __init__(self, scene, node_id: str, service_key: str, model_slug: str):
        self._scene = scene
        self.node_id = node_id
        self.key = f"node:{node_id}"
        self.service_key = service_key
        self.model_slug = model_slug

    def _node(self):
        """The node this slot addresses right now, or None if it is gone."""
        try:
            nodes = getattr(self._scene, "mixie_moodboard_action_nodes", None)
            if not nodes or not self.node_id:
                return None
            for node in nodes:
                if getattr(node, "node_id", "") == self.node_id:
                    return node
        except (ReferenceError, AttributeError):
            # The scene itself was freed (file load); Blender invalidates the
            # Python wrapper, which is the one removal it does report.
            return None
        return None

    def read(self) -> str:
        node = self._node()
        return (getattr(node, "prompt", "") or "") if node is not None else ""

    def write(self, text: str) -> None:
        node = self._node()
        if node is not None:
            node.prompt = text

    def stash(self, original: str) -> None:
        node = self._node()
        if node is None:
            return
        node.prompt_pre_refine = original
        # Two properties, not one: a refinement of an EMPTY-looking prompt is
        # impossible (the button is disabled), but a user can legitimately
        # revert to a prompt that is shorter than the stash cap allows, and
        # "" must not be mistaken for "nothing to revert to".
        node.prompt_refined = True

    def stashed(self) -> str:
        node = self._node()
        if node is None:
            return ""
        return getattr(node, "prompt_pre_refine", "") or ""

    def has_stash(self) -> bool:
        node = self._node()
        return node is not None and bool(getattr(node, "prompt_refined", False))

    def clear_stash(self) -> None:
        node = self._node()
        if node is None:
            return
        node.prompt_pre_refine = ""
        node.prompt_refined = False

    def set_running(self, running: bool) -> None:
        node = self._node()
        if node is not None:
            node.prompt_refining = running

    def is_running(self) -> bool:
        node = self._node()
        return node is not None and bool(getattr(node, "prompt_refining", False))

    def alive(self) -> bool:
        return self._node() is not None


# ---------------------------------------------------------------------------
# Slot resolution
# ---------------------------------------------------------------------------

def sidebar_slot(scene, owner_type: str) -> Optional[SidebarSlot]:
    """The slot behind a sidebar tab prompt, or None if it is not refinable."""
    from .prompt_refine_targets import (
        SIDEBAR_PROMPT_TARGETS,
        resolve_owner,
        sidebar_generation_target,
    )

    target = SIDEBAR_PROMPT_TARGETS.get(owner_type or "")
    if target is None:
        return None
    owner = resolve_owner(scene, target)
    if owner is None:
        return None
    resolved = sidebar_generation_target(scene, owner_type)
    if resolved is None:
        return None
    return SidebarSlot(owner, owner_type, resolved[0], resolved[1])


def node_slot(scene, node_id: str) -> Optional[NodeSlot]:
    """The slot behind a canvas node's prompt, or None.

    The node's OWN saved ``service_key_id``/``model_slug`` strings are used,
    never its dynamic mode/model enums — an enum persists as an index and
    repoints after a catalog reorder, which would refine for whichever
    service happens to sit at that index now.
    """
    nodes = getattr(scene, "mixie_moodboard_action_nodes", None)
    if not nodes or not node_id:
        return None
    for node in nodes:
        if node.node_id != node_id:
            continue
        if not getattr(node, "show_prompt", True):
            return None
        return NodeSlot(
            scene,
            node_id,
            getattr(node, "service_key_id", "") or "",
            getattr(node, "model_slug", "") or "",
        )
    return None


# ---------------------------------------------------------------------------
# Draw-time queries (safe to call from a panel draw)
# ---------------------------------------------------------------------------

def sidebar_can_revert(owner, owner_type: str) -> bool:
    return _sidebar_key(owner, owner_type) in _sidebar_stash


def sidebar_is_refining(owner, owner_type: str) -> bool:
    return _sidebar_key(owner, owner_type) in _sidebar_running


def forget_sidebar_state(owner=None, owner_type: str = "") -> None:
    """Drop stash + in-flight marker for one owner, or all of them.

    Called on file load: a stash belongs to the prompt that was on screen,
    and offering to "revert" a different file's prompt to it would be a data
    loss dressed up as an undo.
    """
    if owner is not None and owner_type:
        key = _sidebar_key(owner, owner_type)
        _sidebar_stash.pop(key, None)
        _sidebar_running.discard(key)
        return
    _sidebar_stash.clear()
    _sidebar_running.clear()


# ---------------------------------------------------------------------------
# Refine / Revert
# ---------------------------------------------------------------------------

def redraw_prompt_surfaces() -> None:
    """Repaint the surfaces a prompt field can live on."""
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type in {'MIXIE', 'VIEW_3D'}:
                    area.tag_redraw()
    except Exception:
        pass


def refine(slot: _Slot, on_done: Callable[[bool, str], None]) -> bool:
    """Send *slot*'s prompt for refinement and replace it with the result.

    ``on_done(success, message)`` fires on Blender's main thread. Returns
    False when the request was not sent at all (empty prompt, or one already
    in flight for this slot) — the caller reports, nothing changed.

    The stash is written from the response's ``original_prompt``, which is
    the exact text the backend refined, not whatever is in the field when the
    answer lands: the user may have kept typing while the call was out, and
    reverting to a prompt that was never refined is not a revert.
    """
    prompt = slot.read().strip()
    if not prompt:
        on_done(False, "Write a prompt first")
        return False
    if slot.is_running():
        return False

    from mixar.modules.common.api.services import get_prompt_refine_service

    slot.set_running(True)
    redraw_prompt_surfaces()

    def _finish(success: bool, message: str) -> None:
        if slot.alive():
            slot.set_running(False)
        redraw_prompt_surfaces()
        on_done(success, message)

    def _on_success(response):
        # The client wraps the whole envelope in response.data; unwrap the
        # inner payload the way the other moodboard services do.
        envelope = getattr(response, "data", None) or {}
        data = envelope.get("data", envelope)
        refined = (data.get("prompt") or "").strip()
        original = data.get("original_prompt") or prompt

        if not refined:
            _finish(False, "Refinement returned nothing — prompt unchanged")
            return
        if not slot.alive():
            _finish(False, "")
            return
        if refined == original:
            # Nothing gained, and offering a Revert would promise an undo of
            # a change that never happened. An EARLIER refinement's stash is
            # left standing — that undo is still real.
            _finish(True, "Prompt is already specific — left unchanged")
            return

        # Refine stays available after a refinement, so this can be the
        # second, third... pass. Only the FIRST one stashes: Revert means
        # "put back what I wrote", never "step back one refinement".
        if not slot.has_stash():
            slot.stash(original)
        slot.write(refined)
        _finish(True, "Prompt refined")

    def _on_error(error):
        logger.error("[PromptRefine] refine failed: %s", error)
        _finish(False, _error_message(error))

    get_prompt_refine_service().refine_async(
        prompt,
        service_key=slot.service_key,
        model_slug=slot.model_slug,
        on_success=_on_success,
        on_error=_on_error,
    )
    return True


def revert(slot: _Slot) -> bool:
    """Put the user's own prompt back. False when there is nothing stashed.

    Also False while a refinement is in flight for this slot: reverting then
    would clear the stash, and the response landing afterwards would see no
    stash and re-stash the CURRENT text — the previous refinement — so the
    user's real wording would be gone for good. Both surfaces keep Revert
    pressable during a refine, so the guard lives here, not in the UI.
    """
    if not slot.alive():
        return False
    if slot.is_running():
        return False
    if not slot.has_stash():
        slot.clear_stash()
        return False
    slot.write(slot.stashed())
    slot.clear_stash()
    redraw_prompt_surfaces()
    return True


def _error_message(error) -> str:
    """User-facing message for a failed refinement.

    409 is not a failure the user can act on — refinement is switched off for
    this target server-side — so it says so plainly instead of inviting a
    retry. Everything else routes through the shared queue classifier (402 →
    out of credits, and so on).
    """
    status = getattr(error, "status_code", None)
    if status == 409:
        return "Prompt refinement is unavailable for this model"
    if status == 502:
        return "Refinement failed — no credits were used, please try again"

    try:
        from mixar.modules.common.job_queue.core.error_helpers import (
            classify_error,
            sanitize_message,
        )
    except Exception:
        # The classifier is a nicety; losing it must not cost the user the
        # only signal that their click did nothing.
        return "Prompt refinement failed"

    return classify_error(error) or sanitize_message(
        str(error), "Prompt refinement failed"
    )
