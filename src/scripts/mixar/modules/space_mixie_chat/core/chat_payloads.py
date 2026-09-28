# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""One command body for every chat entry point."""
from typing import Optional

def build_chat_payload(
    *,
    message: str,
    instance_id: str,
    session_id: str,
    plan_required: bool,
    execution_required: bool,
    approval_required: bool,
    image_attachments: Optional[list] = None,
    attachment_names: Optional[list] = None,
    imported_object_names: Optional[list] = None,
    project_context: Optional[dict] = None,
    mark_context: Optional[dict] = None,
    user_preferences: Optional[dict] = None,
    auto_mode: bool = False,
    scene_context: Optional[dict] = None,
) -> dict:
    """The ``agent.chat`` command body — one shape for a fresh turn and for an
    interjection into an open run (``core/composer_send.py``)."""
    payload = {
        "message": message,
        "instance_id": instance_id,
        "session_id": session_id,
        "plan_required": plan_required,
        "execution_required": execution_required,
        "approval_required": approval_required,
    }

    # Multimodal content when there are image attachments.
    if image_attachments:
        content = [{"type": "text", "text": message}]
        for img in image_attachments:
            mime = img.get("mime_type", "image/png")
            b64 = img.get("base64", "")
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            })
        if len(content) > 1:
            payload["content"] = content

    # Forward resolved bpy.data.images names so the backend can inline
    # them into the user message; entries are positional and may be
    # empty strings when an attachment did not resolve to a name.
    if attachment_names:
        payload["attachment_names"] = [n for n in attachment_names if n]
    # #1268: names of objects an attached model file created in the
    # scene. Names only — the local path never leaves the addon.
    if imported_object_names:
        payload["imported_object_names"] = [n for n in imported_object_names if n]

    if project_context:
        payload["project_context"] = project_context

    # Where the user pointed, resolved against the live scene before
    # it left the client. The backend uses this instead of asking a
    # vision model to locate the region on a render.
    if mark_context:
        payload["mark_context"] = mark_context

    # Session preferences (e.g. the asset-library match threshold) the
    # backend merges into the agent scratchpad for this turn.
    if user_preferences:
        payload["user_preferences"] = user_preferences

    # Auto mode: the agent never asks the user this turn. Written only when
    # on — omitting the field IS false — and on every send, because the
    # backend keeps nothing (docs/modules/agent-chat.md § Auto mode).
    if auto_mode:
        payload["auto_mode"] = True

    # Which tab this turn runs in, and the tab table as the client sees it
    # (parallel scenes). Datablock names only, never a path. The backend
    # logs it as a [SCENES] line and stamps it on the Langfuse trace, so a
    # trace can be tied to a tab without guessing from its content.
    if scene_context:
        payload["scene_context"] = scene_context
    return payload


#: Caps mirrored by the backend schema (modules/agent/schemas/agent_commands.py).
SCENE_CONTEXT_MAX_TABS = 64
SCENE_CONTEXT_NAME_MAX = 64


def _tab_entry(scene, session_id: str) -> dict:
    from ..constants import is_lane_scene
    sid = str(getattr(scene, "mixie_session_id", "") or "")
    entry = {
        "name": str(getattr(scene, "name", "") or "")[:SCENE_CONTEXT_NAME_MAX],
        "session": sid,
        "objects": 0,
        "state": str(getattr(scene, "mixie_chat_state", "") or ""),
        "lane": bool(is_lane_scene(scene)),
        "current": bool(sid) and sid == session_id,
    }
    try:
        entry["objects"] = len(scene.objects)
    except Exception:
        pass
    return entry


def collect_scene_context(session_id: str) -> Optional[dict]:
    """The tab a turn belongs to plus the client's tab table (main-thread
    bpy read). ``None`` when nothing can be read; never raises."""
    try:
        import bpy

        scenes = list(bpy.data.scenes)
        tabs = [_tab_entry(s, session_id) for s in scenes[:SCENE_CONTEXT_MAX_TABS]]
        current = next((t["name"] for t in tabs if t["current"]), "")
        window_scene = ""
        try:
            window = bpy.context.window
            if window is not None and window.scene is not None:
                window_scene = str(window.scene.name)[:SCENE_CONTEXT_NAME_MAX]
        except Exception:
            pass
        if not current:
            # A first message: the session id is minted on this send and the
            # tab is the window's scene.
            current = window_scene
        return {
            "scene": current,
            "window_scene": window_scene,
            "tabs": tabs,
            "truncated": len(scenes) > SCENE_CONTEXT_MAX_TABS,
        }
    except Exception:
        return None


def collect_user_preferences() -> Optional[dict]:
    """Session preferences to forward to the agent (main-thread bpy read).

    Currently the asset-library match threshold set in the Assets workspace —
    the similarity cutoff the modelling lanes use to reuse a library asset
    instead of modelling it. Returns None if the setting isn't available.
    """
    try:
        import bpy

        state = getattr(bpy.context.scene, "mixie_asset_training", None)
        if state is None:
            return None
        return {"asset_match_threshold": round(float(state.match_threshold), 4)}
    except Exception:
        return None
