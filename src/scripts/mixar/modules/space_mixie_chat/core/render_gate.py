# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent scripts do not run while a render runs on Blender's job thread.

An ``INVOKE_DEFAULT`` render (agent preview, scene_render, the user's F12)
evaluates a depsgraph that is registered with the open file, so a main-thread
script that adds, removes or edits data tags that graph while the job thread
rebuilds and evaluates it. 4.1.1 crashed in ``graph_tag_ids_for_visible_update``
mid-video when moodboard inspection created and removed a temporary image.

The executor answers such a script with ``render_in_progress`` immediately. It
never holds the queue (3.4.2's hold stalled every turn): the refusal names the
render so the backend can wait out a short preview and tell the user about a
long one. See docs/render-job-contract.md.
"""

from typing import Optional

from mixar.config.logging_config import get_logger
from mixar.modules.common.agent_execution import pump
from mixar.modules.common.render_coordinator import core as render_slot

logger = get_logger(__name__)

ERROR_TYPE = "render_in_progress"

# Tools whose client scripts only read, so they cannot tag the render's graph.
READ_ONLY_TOOLS = frozenset({
    "list_moodboard_images",
    # Encodes through attachment_compression.encode_blend_image_jpeg, which
    # creates no datablock.
    "inspect_moodboard_image",
    # Replay and busy are answered before scene_render writes anything.
    "render_scene_image",
    "render_scene_video",
})

_RENDERS = {
    "preview": "an agent preview render",
    "scene_image": "a scene image render",
    "scene_video": "a scene video render",
    "other": "a render",
}


def refusal(tool_name: str) -> Optional[dict]:
    """The failure result for a script that must wait for the render, else None."""
    if tool_name in READ_ONLY_TOOLS:
        return None
    kind = render_slot.native_render_kind()
    if kind is None:
        return None
    return {
        "success": False,
        "error": (f"Blender is running {_RENDERS[kind]}; scene scripts are refused "
                  "until it finishes or is cancelled. Nothing was executed."),
        "error_type": ERROR_TYPE,
        "render_kind": kind,
    }


def refuse_during_render(req) -> bool:
    """Answer ``req`` with the refusal and return True while a render runs."""
    result = refusal(req.tool_name)
    if result is None:
        return False
    logger.info("Refusing %s (id: %s): %s render running",
                req.tool_name, req.request_id, result["render_kind"])
    from .jsonrpc_client import get_jsonrpc_client
    pump.respond(get_jsonrpc_client(), req, result)
    return True
