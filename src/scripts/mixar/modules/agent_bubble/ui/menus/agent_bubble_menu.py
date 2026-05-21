# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent bubble menu — content drawn inside the C++ popup overlay.

Layout (top → bottom):
    [drag handle button: click → drag mode]
    [chat history pane, only when history_lines > 0]
    [native multi-line text input]
    [mode dropdown                    send button]

The drag handle is an operator button that invokes a modal drag
operator. After clicking, the cursor changes to scroll-Y and any mouse
motion smoothly resizes the history pane until the user clicks again
to exit. No numeric value is ever shown — the height is implicit in
the popup's size.

The status pill is rendered SEPARATELY by the GPU draw handler in
core/status_pill_draw.py — it floats at the top-left of every editor's
window region, independent of this popup.
"""

import re

import bpy
from bpy.types import Menu, UIList

from mixar.modules.common.utils.ui_utils import draw_multiline_text_input

# Wrap width chosen for the popup's narrow width (42 widget points). At
# default DPI / scale this fits roughly 38–44 chars per line — anything
# wider gets ellipsized by Blender's label widget. Pre-wrapping here
# guarantees the message body fits even on narrow panels.
_WRAP_WIDTH = 40

# Compiled regexes for stripping basic markdown so the popup shows
# clean text instead of the raw "**word**" / "- item" syntax that the
# agent emits. We keep the regex set small — full markdown rendering
# (the chat editor's C++ pipeline) is out of scope here.
_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_MD_ITALIC_RE = re.compile(r"(?<![\*\w])\*(?!\s)(.+?)(?<!\s)\*(?![\*\w])")
_MD_LIST_RE = re.compile(r"^[\-\*]\s+", re.MULTILINE)
_MD_HEADER_RE = re.compile(r"^#+\s+", re.MULTILINE)
_MD_CODE_INLINE_RE = re.compile(r"`(.+?)`")
_MD_LINK_RE = re.compile(r"\[(.+?)\]\((.+?)\)")

# Session states that mean the agent is actively doing something. Used
# by the inline status pill to flip between Idle/Running.
_RUNNING_STATES = {"BUSY", "MODIFYING", "AWAITING_INPUT"}


def _get_status(scene) -> tuple[str, str]:
    state = getattr(scene, "mixie_chat_state", "OFFLINE") or "OFFLINE"
    if state == "OFFLINE":
        return "Disconnected", 'CANCEL'
    if state == "CONNECTING":
        return "Connecting", 'SORTTIME'
    if state in _RUNNING_STATES:
        return "Running", 'RECORD_ON'
    return "Idle", 'RECORD_OFF'


def _strip_markdown(text: str) -> str:
    """Remove the markdown syntax that the agent commonly emits so the
    popup shows readable text. Bold / italic markers drop, list dashes
    become bullets, headers lose their hashes, inline code keeps its
    contents, links collapse to just the link text. Anything we miss
    just renders as-is — minor cosmetic issue, not a crash."""
    if not text:
        return text
    text = _MD_BOLD_RE.sub(r"\1", text)
    text = _MD_ITALIC_RE.sub(r"\1", text)
    text = _MD_LIST_RE.sub("• ", text)
    text = _MD_HEADER_RE.sub("", text)
    text = _MD_CODE_INLINE_RE.sub(r"\1", text)
    text = _MD_LINK_RE.sub(r"\1", text)
    return text


def _draw_status_pill(layout, scene):
    """Render the status pill as a small boxed row at the top-left of
    the popup. Visually reads as a separate floating "bubble" because
    of the layout.box() border, but it's structurally part of THIS
    popup — so it auto-follows the bubble's position when dragged,
    closes with ESC together, etc. The split with a 30 / 70 factor
    pushes the pill to the left third of the popup width and leaves
    the rest empty (same alignment shown in the Figma).
    """
    label, icon = _get_status(scene)

    split = layout.split(factor=0.30)
    pill_cell = split.column()
    split.column()  # right-side empty margin

    box = pill_cell.box()
    inner = box.row()
    inner.scale_y = 0.7
    inner.alignment = 'LEFT'
    inner.label(
        text=label,
        icon=icon,
    )

    # Spacing so the pill visually separates from the drag handle.
    layout.separator(factor=0.4)


def _draw_drag_handle(layout):
    """Centered click-to-toggle handle at the top of the popup.

    Centering trick: a row's children stretch to fill horizontally by
    default, so alignment='CENTER' alone doesn't center an operator
    button (the button just stretches to fill the entire row). Forcing
    centering needs a SPLIT with empty side columns. We use ~40 % left
    and right margins, leaving the button in the middle 20 %.
    """
    row = layout.row()
    row.scale_y = 0.4

    # Three-column layout: empty | button | empty.
    split_left = row.split(factor=0.40, align=True)
    split_left.column()  # left margin (empty)

    inner = split_left.split(factor=1.0 / 3.0, align=True)
    inner.operator(
        "mixar.agent_bubble_drag_history",
        text="━━━",
        emboss=True,
    )
    inner.column()  # right margin (empty)

    # Breathing room between the handle and the next element.
    layout.separator(factor=0.6)


def _wrap_lines(text: str, max_chars: int) -> list[str]:
    """Greedy word-wrap a string into lines no wider than max_chars.

    Used so message bodies fit inside the narrow popup. We split on
    explicit newlines (preserving paragraph breaks) and word-wrap each
    paragraph individually.
    """
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


class MIXIE_CHAT_UL_history(UIList):
    """Scrollable list of chat messages for the floating bubble.

    Using a UIList instead of manual layout rendering gives us scroll
    behavior for free — mouse wheel, trackpad, up/down arrow keys,
    and the scrollbar all just work. The list is bound to
    scene.mixie_chat_messages so every message is reachable; the
    user scrolls within the visible window.

    Each row renders one message as a boxed bubble. Agent messages
    fill the row; user messages are pushed to the right with a left
    margin so they read as opposite-aligned chat bubbles.
    """

    bl_idname = "MIXIE_CHAT_UL_history"

    def draw_item(
        self, context, layout, data, item, icon, active_data, active_propname, index
    ):
        sender = getattr(item, "sender", "USER") or "USER"
        text = (getattr(item, "content", "") or getattr(item, "text", "") or "").strip()
        if not text:
            layout.label(text="")
            return
        text = _strip_markdown(text)
        is_user = sender == "USER"
        wrapped = _wrap_lines(text, _WRAP_WIDTH)

        # User messages on the right (with left margin), agent on the left
        # (full width). Same asymmetric layout as the Figma reference.
        if is_user:
            split = layout.split(factor=0.30)
            split.column()  # left margin
            cell = split.column()
        else:
            cell = layout.column()

        box = cell.box()
        body = box.column(align=True)
        body.scale_y = 0.85
        for line in wrapped:
            row = body.row()
            row.alignment = 'RIGHT' if is_user else 'LEFT'
            row.label(text=line)


def _draw_message_bubble(parent_layout, sender: str, wrapped: list[str]) -> None:
    """One message rendered as a boxed bubble.

    Agent messages get the FULL popup width (the chat reply is the
    primary content). User messages get ~70 % of width pushed to the
    right, with a 30 % empty margin on the left — a subtle visual
    asymmetry that matches the Figma chat layout.
    """
    is_user = sender == "USER"

    if is_user:
        # 30% empty left margin, bubble in the right 70%.
        split = parent_layout.split(factor=0.30)
        split.column()  # margin
        bubble_cell = split.column()
    else:
        # Agent: full width — no split, the bubble fills the popup.
        bubble_cell = parent_layout.column()

    box = bubble_cell.box()
    body = box.column(align=True)
    body.scale_y = 0.85
    for line in wrapped:
        row = body.row()
        row.alignment = 'RIGHT' if is_user else 'LEFT'
        row.label(text=line)


def _draw_history(layout, scene, list_rows: int) -> None:
    """Render the chat history as a scrollable UIList.

    template_list shows the entire scene.mixie_chat_messages collection
    with native scroll support — mouse wheel, trackpad, up/down keys,
    scrollbar drag. The visible row count comes from list_rows (driven
    by the user's drag on the handle); content beyond that scrolls.

    Auto-scrolls to the newest message by setting the active index to
    the last row whenever the message count changes — without that, the
    list would stay fixed at the top while new messages stream in
    below the visible window. Setting the active index in draw is
    safe because UIList scrolls but doesn't trigger redraws.
    """
    messages = getattr(scene, "mixie_chat_messages", None)
    if messages is None:
        return

    # Auto-scroll: keep the list pinned to the most recent message.
    msg_count = len(messages)
    if msg_count > 0:
        target = msg_count - 1
        if scene.mixar_bubble_history_active_index != target:
            scene.mixar_bubble_history_active_index = target

    layout.template_list(
        "MIXIE_CHAT_UL_history", "",
        scene, "mixie_chat_messages",
        scene, "mixar_bubble_history_active_index",
        rows=max(3, min(list_rows, 12)),
        type='DEFAULT',
    )


class MIXIE_CHAT_MT_agent_bubble(Menu):
    """Body of the floating agent bubble popup."""

    bl_idname = "MIXIE_CHAT_MT_agent_bubble"
    bl_label = "Agent"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # Status pill — visually a separate bubble (boxed), structurally
        # part of this popup so it follows the bubble's drag and ESC.
        _draw_status_pill(layout, scene)

        # Drag handle button below the pill.
        _draw_drag_handle(layout)

        # History pane: rendered when the user has dragged the handle
        # to expose any positive line count. Stays empty if there are
        # no messages yet — but the popup still grows in proportion to
        # the drag distance.
        history_lines = (
            getattr(scene, "mixar_bubble_history_lines", 0) if scene else 0
        )
        if history_lines > 0:
            _draw_history(layout, scene, list_rows=history_lines)
            layout.separator(factor=0.7)

        # Native multi-line input — same widget the chat editor's footer
        # uses. Word-wrap, vertical scroll, Shift+Enter for newline,
        # Enter to submit (the chat-editor's update callback on
        # mixie_chat_input detects the \x1F submit marker and fires
        # the send operator).
        input_col = layout.column()
        if scene is not None:
            draw_multiline_text_input(
                input_col,
                scene,
                "mixie_chat_input",
                text="",
                min_lines=2,
                max_lines=6,
            )

        # Mode dropdown + send button row.
        action_row = layout.row(align=True)
        action_row.scale_y = 1.2

        if scene is not None and hasattr(scene, "mixie_chat_mode"):
            action_row.prop(scene, "mixie_chat_mode", text="")

        action_row.separator_spacer()

        action_row.operator(
            "mixie_chat.send_message",
            text="Send",
            icon='PLAY',
        )


classes = (
    MIXIE_CHAT_UL_history,
    MIXIE_CHAT_MT_agent_bubble,
)
