# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Keep images visible to Codex's model.

When a direct MCP call returns ``structuredContent``, Codex sends its model only
that JSON and drops the content blocks, images included (codex-rs
``protocol/src/models.rs``, ``CallToolResult::as_function_call_output_payload``).
Code-mode calls hand the whole result to the model's script and do show images.
For clientInfo ``codex-mcp-client``, a result carrying images therefore omits
``structuredContent``: both routes then give the model the full text and the
pictures (renders, UI observations).

A tool that declares an outputSchema must return structuredContent, so Codex is
not sent output schemas at all (``tools_for_client``); it reads them only as
code-mode type hints, and its code-mode scripts receive the whole result anyway.

The content text is never shortened: a code-mode script prints whatever it
reads, and replay against Codex 0.160 showed a summary line hiding the result
from the model. Every other client gets results unchanged.
"""

CODEX_CLIENTS = frozenset({"codex-mcp-client"})


def client_name(ctx):
    params = getattr(getattr(ctx, "session", None), "client_params", None)
    info = getattr(params, "client_info", None)
    return getattr(info, "name", "") or ""


def client_info(ctx):
    """The AI app's clientInfo, bounded, for content-free usage attribution."""
    params = getattr(getattr(ctx, "session", None), "client_params", None)
    info = getattr(params, "client_info", None)
    return {"name": str(getattr(info, "name", "") or "")[:80],
            "version": str(getattr(info, "version", "") or "")[:24]}


def for_client(result, name):
    """``result`` is a CallToolResult as a JSON dict; returns the dict to send."""
    if (name in CODEX_CLIENTS and result.get("structuredContent") is not None
            and any(block.get("type") == "image" for block in result.get("content") or [])):
        return {key: value for key, value in result.items() if key != "structuredContent"}
    return result


def tools_for_client(tools, name):
    """Tool definitions as listed to ``name``: no output schemas for Codex."""
    if name not in CODEX_CLIENTS:
        return tools
    return [{key: value for key, value in tool.items() if key != "outputSchema"} for tool in tools]
