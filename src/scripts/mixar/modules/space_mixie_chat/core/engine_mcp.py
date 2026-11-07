# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unreal's editor toolsets, passed through to the agent as Claude sees them.

Unreal 5.8's editor MCP server exposes three tools — ``list_toolsets``,
``describe_toolset`` and ``call_tool`` — and every Epic toolset (assets,
scene, materials, Sequencer, PCG, …) is reached through them by progressive
disclosure. The backend's ``engine_list_toolsets`` / ``engine_describe_toolset``
/ ``engine_call_tool`` reach this module through a two-line script, exactly
as the ``engine_*`` tools reach ``engine_link``, so ``engine_prefetch`` makes
the call on a worker thread and the script takes the stored answer.

The pass-through has no allow- or denylist (every toolset and tool is
callable, as for Claude), never saves on its own (the agent saves explicitly)
and is not bound by Mixar Link's plugin mode, which guards only Mixar's own
wrappers. Arguments go to Unreal verbatim; every string coming back is
scrubbed of absolute local paths (``engine_link.scrub``), errors included.
Images (MCP image items, or ``{mimeType: "image/…", data}`` objects inside a
toolset's JSON answer, as Epic's capture tools send) come back as ``images``
— at most three — and never as base64 inside the text result.

Godot has no editor toolsets: the three calls refuse there.

Every function answers ``{"success", "data", "error"?, "images"?}`` and never
raises.
"""

from __future__ import annotations

import json

from . import engine_link

ENGINE_MCP_CAPABILITY = "engine_mcp_v1"
GODOT_REFUSAL = "Godot has no editor toolsets; use the engine_* tools."
LIST_TIMEOUT_S = 30.0
# describe_toolset's JSON above this many characters comes back compact
# (Sequencer's is ~125,000): names + first description lines, and the agent
# asks for the tools it needs with ``tools=[…]``.
DESCRIBE_LIMIT = 40_000
# A call's JSON-encoded result above this is cut (long lists, long strings).
RESULT_LIMIT = 60_000
MAX_IMAGES = 3
# Images reach the model at most this long on their longer side, and this
# heavy once encoded (``fit_image``).
MAX_IMAGE_SIDE = 1568
MAX_IMAGE_BYTES = 1_500_000
ERROR_LIMIT = 20_000
CALL_TIMED_OUT = ("Unreal did not answer in time; the call may still have completed. "
                  "Check the editor's state before repeating it.")


def _client(engine):
    """The Unreal client, or LinkError (no engine, or Godot)."""
    info, client = engine_link._connect(engine)
    if info.get("transport") != engine_link.UNREAL_TRANSPORT:
        raise engine_link.LinkError(GODOT_REFUSAL)
    return client


def _top(client, name: str, arguments: dict, timeout: float) -> dict:
    # The server's own top-level tool: through the BASE client, never
    # UnrealMcpClient.call, which wraps every call into Mixar Link's toolset.
    return engine_link.McpClient.call(client, name, arguments, timeout)


def _texts(raw: dict) -> list:
    content = raw.get("content") if isinstance(raw.get("content"), list) else []
    return [str(c.get("text") or "") for c in content if isinstance(c, dict) and c.get("type") == "text"]


def fit_image(data: str, mime: str) -> dict:
    """``{"data", "mime"}`` small enough to hand a model: Epic's
    ``CaptureViewport`` answers the viewport at full size (a 2545x1910 PNG is
    6 MB of base64), so an image longer than ``MAX_IMAGE_SIDE`` px is scaled
    down and one still over ``MAX_IMAGE_BYTES`` is re-encoded as JPEG. Runs on
    the engine worker thread (never Blender's). Unchanged when Pillow is
    missing or the bytes do not decode."""
    try:
        import base64
        import io
        from PIL import Image
        raw = base64.b64decode(data)
        with Image.open(io.BytesIO(raw)) as im:
            im.load()
            if max(im.size) <= MAX_IMAGE_SIDE and len(raw) <= MAX_IMAGE_BYTES:
                return {"data": data, "mime": mime}
            im.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
            out = io.BytesIO()
            im.save(out, format="PNG", optimize=True)
            if out.tell() > MAX_IMAGE_BYTES:
                out = io.BytesIO()
                im.convert("RGB").save(out, format="JPEG", quality=85)
                mime = "image/jpeg"
            else:
                mime = "image/png"
        return {"data": base64.b64encode(out.getvalue()).decode("ascii"), "mime": mime}
    except Exception:  # noqa: BLE001 - an image that cannot be fitted goes as it came
        return {"data": data, "mime": mime}


def _content_images(raw: dict, images: list) -> None:
    content = raw.get("content") if isinstance(raw.get("content"), list) else []
    for c in content:
        if isinstance(c, dict) and c.get("type") == "image" and isinstance(c.get("data"), str):
            if len(images) < MAX_IMAGES:
                images.append(fit_image(c["data"], str(c.get("mimeType") or "image/png")))


def _error(raw: dict) -> str:
    text = "\n".join(t for t in _texts(raw) if t).strip() or "Unreal reported an error."
    return engine_link.scrub(text[:ERROR_LIMIT])


def lift_images(value, images: list):
    """``value`` with every ``{mimeType: "image/…", data: <base64>}`` object
    replaced by ``{mimeType, attached}``; the first ``MAX_IMAGES`` go into
    ``images`` (``attached: false`` past that)."""
    if isinstance(value, dict):
        mime = value.get("mimeType")
        if isinstance(mime, str) and mime.startswith("image/") and isinstance(value.get("data"), str):
            attached = len(images) < MAX_IMAGES
            if attached:
                images.append(fit_image(value["data"], mime))
            return {"mimeType": mime, "attached": attached}
        return {k: lift_images(v, images) for k, v in value.items()}
    if isinstance(value, list):
        return [lift_images(v, images) for v in value]
    return value


def _parse(text: str):
    """A text item as the tool meant it: ``returnValue`` of a Python
    toolset's JSON (itself parsed when it is a JSON string), other JSON, or
    the text."""
    try:
        value = json.loads(text)
    except ValueError:
        return text
    if isinstance(value, dict) and set(value) == {"returnValue"}:
        value = value["returnValue"]
        if isinstance(value, str) and value.strip()[:1] in ("{", "["):
            try:
                value = json.loads(value)
            except ValueError:
                pass
    return value


def _size(value) -> int:
    return len(json.dumps(value, default=str))


def _shrink(value, items: int, chars: int, path: str, totals: dict):
    if isinstance(value, str):
        return value if len(value) <= chars else value[:chars] + f"… [{len(value) - chars} more characters]"
    if isinstance(value, list):
        if len(value) > items:
            totals[path] = len(value)
        return [_shrink(v, items, chars, f"{path}[{i}]", totals) for i, v in enumerate(value[:items])]
    if isinstance(value, dict):
        return {k: _shrink(v, items, chars, f"{path}.{k}", totals) for k, v in value.items()}
    return value


def cap(value, limit: int = RESULT_LIMIT):
    """(value, totals): ``value`` cut until its JSON fits ``limit`` — lists
    keep their first items, strings their start. ``totals`` maps each cut
    list (``result.actors``) to its full length; None when nothing was cut."""
    if _size(value) <= limit:
        return value, None
    items, chars = 200, 20_000
    while True:
        totals: dict = {}
        out = _shrink(value, items, chars, "result", totals)
        if _size(out) <= limit or (items <= 1 and chars <= 200):
            return out, totals
        items, chars = max(1, items // 2), max(200, chars // 2)


def _compact(described: dict) -> dict:
    tools = described.get("tools") if isinstance(described.get("tools"), list) else []
    short = []
    for t in tools:
        if isinstance(t, dict):
            first = str(t.get("description") or "").strip().splitlines()
            short.append({"name": t.get("name"), "description": first[0] if first else ""})
    return {**{k: v for k, v in described.items() if k != "tools"}, "tools": short, "truncated": True,
            "note": "Descriptions shortened; pass tools=[…] for the full input schemas."}


def split_tool_name(tool_name, toolset_name="") -> tuple[str, str]:
    """``(toolset_name, tool_name)`` as Unreal's ``call_tool`` takes them: the
    toolset apart and the tool WITHOUT its toolset prefix ("Tool '….SceneTools.
    add_to_scene_from_asset' not found" otherwise, live 5.8.3). describe_toolset
    names tools in full, so a full name splits at its last dot; a name repeating
    the given toolset loses the prefix. A bare name with no toolset stays a
    top-level tool."""
    tool_name, toolset_name = str(tool_name or "").strip(), str(toolset_name or "").strip()
    if toolset_name:
        if tool_name.startswith(toolset_name + "."):
            tool_name = tool_name[len(toolset_name) + 1:]
        return toolset_name, tool_name
    if "." in tool_name:
        toolset_name, _, tool_name = tool_name.rpartition(".")
    return toolset_name, tool_name


def _matches(name, wanted: set) -> bool:
    name = str(name or "")
    short = name.rsplit(".", 1)[-1]
    return bool({name, short, name.lower(), short.lower()} & wanted)


# ---------------------------------------------------------------------------
# Called by the backend (agent scripts)
# ---------------------------------------------------------------------------

@engine_link._prefetchable
def link_mcp_list_toolsets(engine: str | None = None) -> dict:
    """Every toolset Unreal's editor offers, as the server's own text."""
    try:
        client = _client(engine)
        raw = _top(client, "list_toolsets", {}, LIST_TIMEOUT_S)
    except engine_link.LinkError as err:
        return engine_link._fail(err)
    if raw.get("isError"):
        return {"success": False, "error": _error(raw)}
    data = {"toolsets": engine_link.scrub("\n".join(_texts(raw)))}
    instructions = getattr(client, "instructions", "")
    if instructions:
        data["instructions"] = engine_link.scrub(str(instructions))
    return {"success": True, "data": data}


@engine_link._prefetchable
def link_mcp_describe(toolset_name: str, tools: list | None = None, engine: str | None = None) -> dict:
    """One toolset's JSON (``name``, ``version``, ``description``, ``tools``
    with schemas). ``tools`` (short or full names) keeps those tools only;
    unfiltered and over ``DESCRIBE_LIMIT`` it comes back compact."""
    try:
        raw = _top(_client(engine), "describe_toolset", {"toolset_name": str(toolset_name or "")},
                   LIST_TIMEOUT_S)
    except engine_link.LinkError as err:
        return engine_link._fail(err)
    if raw.get("isError"):
        return {"success": False, "error": _error(raw)}
    text = "\n".join(_texts(raw))
    try:
        described = json.loads(text)
    except ValueError:
        described = None
    if not isinstance(described, dict):
        return {"success": True, "data": {"text": engine_link.scrub(text)}}
    if tools:
        wanted = {str(t) for t in tools} | {str(t).lower() for t in tools}
        kept = [t for t in described.get("tools") or [] if isinstance(t, dict) and _matches(t.get("name"), wanted)]
        found = {n for t in kept for n in (str(t.get("name")), str(t.get("name")).rsplit(".", 1)[-1])}
        found |= {n.lower() for n in found}
        described = {**described, "tools": kept}
        missing = [str(t) for t in tools if str(t) not in found and str(t).lower() not in found]
        if missing:
            described["missing"] = missing
        described, totals = cap(described)
        if totals is not None:
            described["truncated"] = True
    elif len(text) > DESCRIBE_LIMIT:
        described = _compact(described)
    return {"success": True, "data": engine_link.scrub(described)}


@engine_link._prefetchable
def link_mcp_call(tool_name: str, toolset_name: str = "", arguments: dict | None = None,
                  engine: str | None = None, timeout: float = 60.0) -> dict:
    """One Epic tool through the server's ``call_tool``; ``result`` is its
    ``returnValue`` (or the JSON / text it answered)."""
    try:
        timeout = min(max(float(timeout or 60.0), 1.0), 600.0)
    except (TypeError, ValueError):
        timeout = 60.0
    toolset_name, tool_name = split_tool_name(tool_name, toolset_name)
    args = {"tool_name": tool_name, "arguments": arguments if isinstance(arguments, dict) else {}}
    if toolset_name:
        args["toolset_name"] = toolset_name
    try:
        raw = _top(_client(engine), "call_tool", args, timeout)
    except engine_link.LinkError as err:
        if err.timed_out:
            return {"success": False, "error": CALL_TIMED_OUT}
        return engine_link._fail(err)
    if raw.get("isError"):
        return {"success": False, "error": _error(raw)}
    images: list = []
    _content_images(raw, images)
    texts = [t for t in _texts(raw) if t]
    if texts:
        result = _parse(texts[0]) if len(texts) == 1 else [_parse(t) for t in texts]
    elif isinstance(raw.get("structuredContent"), dict):
        result = raw["structuredContent"].get("returnValue", raw["structuredContent"])
    else:
        result = None
    result = lift_images(result, images)
    result, totals = cap(engine_link.scrub(result))
    data = {"result": result}
    if totals is not None:
        data["truncated"] = True
        data["total"] = totals
    out = {"success": True, "data": data}
    if images:
        out["images"] = images
    return out
