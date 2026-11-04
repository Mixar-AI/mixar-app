# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Connect MCP — the sheet's frame, header, sidebar and shared rows.

The same native sheet as AI Provider settings (`common/sheet/kit`): title
and subtitle over the header divider, the APPS sidebar (one row per
`app_configs.SIDEBAR` app, a Guide pill, the "Other app" foot with its
terminal glyph) and a right column whose plan (`connect_sheet_plans`)
follows ``wm.mixar_mcp_dialog_state``:

  IDLE / ERROR / ADDING  the form (FormPlan)
  ADDED                  the recap with one Done (RecapPlan)
  signed out             what MCP needs and Sign in (SignedOutPlan)

The one-action contract: every state marks exactly ONE button as the
dialog's active default, which keeps the props dialog's OK/Cancel row away;
the ✕ and Done are cancel-path dismisses. This module only draws; state
lives on WindowManager (`ui/properties/connect_props.py`,
`core/connect_state.py`).
"""

from mixar.modules.common.i18n import iface_, n_
from mixar.modules.common.sheet import kit as S

from ...constants import OTHER_APP, SETUP_GUIDE_URL
from ...core import app_configs, runtime
from ...core.connect_state import BUSY_STATES

OP_PICK_APP = "mixar.mcp_pick_app"
OP_PICK_FORMAT = "mixar.mcp_pick_format"
OP_ADD = "mixar.mcp_add_to_app"
OP_COPY = "mixar.copy_mcp_setup"
OP_OPEN = "mixar.mcp_open_app_config"
OP_ENABLE = "mixar.set_mcp_enabled"
OP_UI_CONTROL = "mixar.set_mcp_ui_control"
OP_LOGIN = "mixie_chat.login"
GUIDE_URL = SETUP_GUIDE_URL

# The sheet's width in UI px (the artboard is a 2x export).
SHEET_WIDTH = S.WIDTH // 2
# Design px a text line of the right column may use (from the prompt inset).
TEXT_WIDTH = S.WIDTH - S.RIGHT_X - S.PROMPT_INSET - S.RIGHT_MARGIN
STRIP_GAP = 10           # between the status line and the switch row
FOOT_GAP = 26            # above the action block's prompt


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def draw_dialog(layout, wm, signed_in, ready):
    """`mixar.connect_ai`'s draw(): ``signed_in`` / ``ready`` are the
    operator module's `_signed_in` / `_ready` (an account, and AI apps can
    reach this Mixar right now)."""
    from . import connect_sheet_plans as plans

    layout.use_property_split = False
    layout.use_property_decorate = False
    state = wm.mixar_mcp_dialog_state

    sheet = layout.column(align=True)
    if hasattr(sheet, 'mixar_sheet_frame'):
        sheet.mixar_sheet_frame(header=S.HEADER, sidebar=S.SIDEBAR)
    _draw_header(sheet, state)

    plan = plans.plan_for(sheet, wm, state, signed_in, ready)
    geo = S.Geometry(len(app_configs.SIDEBAR), plan.need, plan.bottom)
    body = sheet.split(factor=S.SPLIT_FACTOR, align=True)
    draw_sidebar(body.column(align=True), wm, geo,
                 enabled=signed_in and state in ('IDLE', 'ERROR'))
    plan.build(S.fixed(body.column(align=True), geo.right), geo)


def _draw_header(sheet, state):
    header = sheet.row(align=True)
    title = header.row(align=True)
    title.scale_y = S.units(S.HEADER)
    S.label(title,
            iface_("Connect MCP") + "\n"
            + iface_("Let Claude, Codex, Cursor and other MCP apps use your Mixar scenes - "
                     "they bring their own model."),
            S.TITLE, translate=False)
    if state in BUSY_STATES:
        # An add in flight keeps the sheet until it lands.
        return
    # The ✕: a cancel-path dismiss in a CLOSE-wide slot reaching down from
    # the sheet's top edge (see byok_dialog_ui._draw_header).
    slot = S.sized(header, S.CLOSE)
    slot.scale_y = S.units(S.CLOSE_TOP + S.CLOSE)
    S.dismiss(slot, S.CLOSE_GLYPH, S.CLOSE_KIND)
    S.gap(header, S.CLOSE_RIGHT)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def draw_sidebar(col, wm, geo, enabled):
    """APPS with the Guide pill, one row per app, the "Other app" foot."""
    body = S.fixed(col, geo.left_body)
    body.enabled = enabled
    S.sep(body, S.CAPTION_TOP)
    head = S.row(body, S.CAPTION_H, left=S.LEFT_INSET, right=S.ROW_RIGHT)
    S.label(head, n_("APPS"), S.CAPTION)
    text = iface_("Guide")
    S.button(S.sized(head, S.text_width(head, S.SECONDARY, text) + S.BUTTON_PAD),
             "wm.url_open", text, S.SECONDARY).url = GUIDE_URL
    S.sep(body, S.CAPTION_TO_ROWS)
    current = wm.mixar_mcp_dialog_app
    for key in app_configs.SIDEBAR:
        name = app_configs.label(key)  # a product name: never translated
        S.choice(S.row(body, S.ROW_H, left=S.LEFT_INSET, right=S.row_right(body, name)),
                 OP_PICK_APP, name, S.PROVIDER_ROW, lit=(key == current), app=key)

    foot = S.fixed(col, S.FOOTER)
    foot.enabled = enabled
    S.choice(S.row(foot, S.ROW_H, left=S.LEFT_INSET, right=S.ROW_RIGHT), OP_PICK_APP,
             iface_("Other app"), S.FOOTER_ROW, lit=(current == OTHER_APP),
             extra=S.FOOT_TERMINAL, app=OTHER_APP)
    S.sep(foot, S.FOOTER - S.ROW_H)


# ---------------------------------------------------------------------------
# Rows the plans share
# ---------------------------------------------------------------------------

def pill(line, operator_id, text, kind=S.SECONDARY):
    """A strip pill sized to its label."""
    return S.button(S.sized(line, S.text_width(line, kind, text) + S.BUTTON_PAD),
                    operator_id, text, kind)


def status_text(on, ready):
    """(dot state, text, text kind) of the MCP status line."""
    if not on:
        return (S.STATUS_DANGER, iface_("MCP is off · AI apps report Mixar as not connected"),
                S.DANGER_TEXT)
    if ready:
        return S.STATUS_ON, iface_("MCP is on · AI apps can connect to this Mixar"), S.BODY
    return (S.STATUS_DIM,
            iface_("MCP is on · AI apps can use Mixar once it's signed in and connected"), S.BODY)


def status_pill_text(on):
    return iface_("Turn off") if on else iface_("Turn on")


def status_lines(layout, on, ready):
    """The status text wrapped beside its dot and pill (a long translation
    takes a second strip rather than an ellipsis)."""
    _dot, text, kind = status_text(on, ready)
    pill_kind = S.DANGER_BUTTON if on else S.SECONDARY
    room = (TEXT_WIDTH - S.STATUS_DOT - S.STATUS_GAP - S.GAP
            - S.text_width(layout, pill_kind, status_pill_text(on)) - S.BUTTON_PAD)
    return S.wrap(layout, kind, text, room) or [text]


def draw_status(col, lines, on, ready, busy):
    """The MCP status line: dot, what AI apps see now, Turn off / Turn on
    (hidden while an add runs)."""
    dot, _text, kind = status_text(on, ready)
    for index, line in enumerate(lines):
        strip = S.row(col, S.STRIP_H, left=S.PROMPT_INSET, right=S.RIGHT_MARGIN)
        if index:
            S.gap(strip, S.STATUS_DOT + S.STATUS_GAP)
        else:
            S.status_dot(strip, dot)
        S.label(strip, line, kind, translate=False)
        if index or busy:
            continue
        S.gap(strip, S.GAP)
        if on:
            pill(strip, OP_ENABLE, status_pill_text(on), S.DANGER_BUTTON).enabled = False
        else:
            pill(strip, OP_ENABLE, status_pill_text(on)).enabled = True


def switch_note_fits(layout):
    """Whether the switch's dim note fits beside it; otherwise it takes its own line."""
    used = (S.SWITCH_W + S.SWITCH_GAP + S.GAP
            + S.text_width(layout, S.SWITCH, iface_("Let AI apps control Mixar's interface")))
    return used + S.text_width(layout, S.NOTE, _switch_note()) <= TEXT_WIDTH


def _switch_note():
    return iface_("· your mouse or keyboard always takes over")


def draw_switch(col, enabled, note_beside):
    """Interface control: a switch (off unless MCP is on and the user said
    yes), disabled while MCP is off or an add runs."""
    S.sep(col, STRIP_GAP)
    line = S.row(col, S.STRIP_H, left=S.PROMPT_INSET, right=S.RIGHT_MARGIN)
    line.enabled = enabled
    on = runtime.ui_control_enabled()
    S.switch(line, OP_UI_CONTROL, iface_("Let AI apps control Mixar's interface"),
             on).enabled = not on
    if note_beside:
        S.gap(line, S.GAP)
        S.label(line, _switch_note(), S.NOTE, translate=False)
        return
    under = S.row(col, S.NOTE_H, left=S.PROMPT_INSET + S.SWITCH_W + S.SWITCH_GAP,
                  right=S.RIGHT_MARGIN)
    under.enabled = enabled
    S.label(under, _switch_note(), S.NOTE, translate=False)


def foot(col, prompt, note_lines):
    """The action block: prompt, note, then a right-aligned row for the pills."""
    S.sep(col, FOOT_GAP)
    S.label(S.row(col, S.PROMPT_H, left=S.PROMPT_INSET, right=S.RIGHT_MARGIN), prompt,
            S.PROMPT, translate=False)
    for note in note_lines:
        S.label(S.row(col, S.NOTE_H, left=S.PROMPT_INSET, right=S.RIGHT_MARGIN), note,
                S.NOTE, translate=False)
    S.sep(col, S.NOTE_TO_INPUT)
    return S.row(col, S.INPUT_H, left=S.RIGHT_INSET, right=S.RIGHT_MARGIN, align='RIGHT')


def foot_height(note_lines):
    return S.key_block_height(FOOT_GAP + max(0, len(note_lines) - 1) * S.NOTE_H)


def secondary(line, operator_id, text, enabled=True):
    slot = S.sized(line, S.text_width(line, S.SECONDARY, text) + 2 * S.BUTTON_PAD)
    slot.enabled = enabled
    props = S.button(slot, operator_id, text, S.SECONDARY)
    S.gap(line, S.GAP)
    return props


def primary(line, operator_id, text, enabled=True):
    """The state's one default button (a disabled busy pill keeps the slot)."""
    slot = S.sized(line, max(S.SAVE_W, S.text_width(line, S.PRIMARY, text) + 2 * S.BUTTON_PAD))
    slot.enabled = enabled
    return S.button(slot, operator_id, text, S.PRIMARY, default=True)


# Auto-discovery imports every file under ui/ — nothing to register here.
classes = ()
