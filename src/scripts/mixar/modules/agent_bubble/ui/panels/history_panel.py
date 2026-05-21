# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent Bubble — chat history panel.

Renders inside the AGENT_BUBBLE editor's WINDOW region as a single
panel that shows every message from scene.mixie_chat_messages. The
WINDOW region uses ED_region_panels_layout (set in
src/source/blender/editors/space_agent_bubble/space_agent_bubble.cc),
so it has a built-in View2D — that's what gives us native scroll
behavior:

    Mouse wheel       → View2D scroll
    Trackpad          → View2D scroll (vertical / horizontal)
    Up / Down arrows  → View2D scroll-step
    Scrollbar drag    → View2D scroll

The chat editor's queue processor mutates message.content chunk-by-
chunk during streaming. We don't need a polling timer here because
the panel re-draws whenever the scene's notifier fires, which happens
on every property update from the chat backend.

Messages are rendered chronologically (oldest top, newest bottom).
User-visible messages are right-aligned with a left margin; agent
messages span the full width on the left. Markdown syntax (**bold**,
- lists, # headers, `code`, [link](url)) is stripped to clean text;
full markdown rendering is the chat editor's job, not ours.
"""

import re

import bpy
from bpy.types import Panel


# ---------------------------------------------------------------------------
# Markdown stripping (small, on-purpose — we just clean the obvious symbols).
# ---------------------------------------------------------------------------

_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_MD_ITALIC_RE = re.compile(r"(?<![\*\w])\*(?!\s)(.+?)(?<!\s)\*(?![\*\w])")
_MD_LIST_RE = re.compile(r"^[\-\*]\s+", re.MULTILINE)
_MD_HEADER_RE = re.compile(r"^#+\s+", re.MULTILINE)
_MD_CODE_INLINE_RE = re.compile(r"`(.+?)`")
_MD_LINK_RE = re.compile(r"\[(.+?)\]\((.+?)\)")


def _strip_markdown(text: str) -> str:
    if not text:
        return text
    text = _MD_BOLD_RE.sub(r"\1", text)
    text = _MD_ITALIC_RE.sub(r"\1", text)
    text = _MD_LIST_RE.sub("• ", text)
    text = _MD_HEADER_RE.sub("", text)
    text = _MD_CODE_INLINE_RE.sub(r"\1", text)
    text = _MD_LINK_RE.sub(r"\1", text)
    return text


# Width tuned for a typical Agent Bubble editor area. Blender's label
# widget doesn't word-wrap, so we pre-wrap to a fixed character width
# (anything longer ellipsizes). 60 chars fits comfortably in a
# moderately-sized editor; users can resize the area for more room.
_WRAP_WIDTH = 60


def _wrap_lines(text: str, max_chars: int) -> list[str]:
    if not text:
        return []
    out: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph:
            out.append("")
            continue
        words = paragraph.split(" ")
        current = ""
        for word in words:
            candidate = word if not current else current + " " + word
            if len(candidate) <= max_chars or not current:
                current = candidate
            else:
                out.append(current)
                current = word
        if current:
            out.append(current)
    return out


def _draw_message(parent_layout, sender: str, wrapped: list[str]) -> None:
    """Render one message as a boxed bubble.

    User → right side with a 30 % left margin.
    Agent → full width on the left.
    """
    is_user = sender == "USER"
    if is_user:
        split = parent_layout.split(factor=0.30)
        split.column()  # left margin (empty)
        cell = split.column()
    else:
        cell = parent_layout.column()

    box = cell.box()
    body = box.column(align=True)
    body.scale_y = 0.85
    for line in wrapped:
        row = body.row()
        row.alignment = 'RIGHT' if is_user else 'LEFT'
        row.label(text=line)


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

class AGENT_BUBBLE_PT_history(Panel):
    """Chat history list for the floating Agent Bubble editor."""

    bl_idname = "AGENT_BUBBLE_PT_history"
    bl_space_type = 'AGENT_BUBBLE'
    bl_region_type = 'WINDOW'
    bl_label = ""
    bl_options = {'HIDE_HEADER'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        if scene is None:
            layout.label(text="(No scene)")
            return

        # When the body region is at its collapsed minimum (~30 px,
        # Blender's WINDOW-region floor), render NOTHING. Otherwise
        # the boot state shows a "No messages yet" placeholder
        # squashed into a 30-px strip that visually competes with
        # the header and footer for attention. Blank strip is the
        # cleanest visual for the collapsed bubble.
        region = context.region
        if region is not None and region.height < 60:
            return

        messages = getattr(scene, "mixie_chat_messages", None)
        if messages is None:
            # Property doesn't exist — chat module hasn't registered
            # mixie_chat_messages yet, or scope mismatch. Surface this
            # rather than going blank so the user knows what's wrong.
            warn = layout.column()
            warn.scale_y = 0.85
            warn.label(
                text="(Chat backend not ready — mixie_chat_messages unavailable)",
                icon='ERROR',
            )
            return

        if len(messages) == 0:
            empty = layout.column()
            empty.scale_y = 0.85
            empty.label(text="No messages yet — type below to start.", icon='INFO')
            return

        # Render chronologically: oldest at top, newest at the bottom
        # (right above the input). Standard chat ordering. The View2D
        # in the WINDOW region handles scrolling — user can wheel /
        # trackpad / arrow-key / scrollbar to navigate.
        #
        # CRITICAL: do NOT skip messages with empty content. The chat
        # backend pre-allocates an empty message slot when the agent
        # starts replying, then streams content into it chunk by chunk.
        # Between chunks (and at the moment the slot is created),
        # content may be empty. Skipping empty messages here is what
        # caused the panel to flash blank during streaming. We render
        # an ellipsis placeholder instead so the message bubble is
        # always visible and updates in place as content arrives.
        history = layout.column(align=False)
        rendered = 0
        for msg in messages:
            try:
                sender = getattr(msg, "sender", "USER") or "USER"
                raw = (
                    getattr(msg, "content", "")
                    or getattr(msg, "text", "")
                    or ""
                ).strip()
                if raw:
                    cleaned = _strip_markdown(raw)
                    wrapped = _wrap_lines(cleaned, _WRAP_WIDTH) or ["…"]
                else:
                    # Empty (still streaming or just created) — show
                    # an ellipsis bubble as the typing indicator.
                    wrapped = ["…"]
                _draw_message(history, sender, wrapped)
                history.separator(factor=0.3)
                rendered += 1
            except Exception as e:  # noqa: BLE001 — never blank the whole panel
                history.label(
                    text=f"(failed to render message: {e})",
                    icon='ERROR',
                )

        if rendered == 0:
            # Iteration produced nothing visible — surface the count so
            # we can diagnose rather than show a silent empty body.
            layout.label(
                text=f"({len(messages)} messages but none rendered)",
                icon='SORTTIME',
            )


classes = (AGENT_BUBBLE_PT_history,)
