# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Refer a Friend dialog — drawing only.

Same design language as the AI Provider Settings dialog: profile-card text
painters (``mixar_card_label``), card action buttons (``mixar_card_button``)
and the ``mixar_section`` / ``mixar_input`` widgets, each degrading to stock
widgets on a build whose C++ predates them.

One-action contract: every state marks exactly one footer button as the
active default, which suppresses the native OK/Cancel row
(``wm_block_dialog_create`` only adds it when nothing holds that flag).
"""

from mixar.modules.common.ui.constants import (
    CARD_ROW_CTA,
    CARD_ROW_DIVIDER,
    CARD_ROW_FIELD,
)

from ... import constants as C
from ...core.invites import format_credits

OP_COPY = "mixar.referral_copy_link"
OP_SEND = "mixar.referral_send_invites"
OP_RELOAD = "mixar.referral_reload"


def card_label(layout, text, kind='MUTED'):
    if hasattr(layout, 'mixar_card_label'):
        layout.mixar_card_label(text=text, kind=kind)
        return
    if kind == 'DIVIDER':
        layout.separator()
        return
    row = layout.row()
    row.enabled = kind not in ('MUTED', 'SECTION', 'META')
    row.alert = kind == 'DANGER'
    row.label(text=text)


def _style_last(layout, kind='CARD', default=False):
    if hasattr(layout, 'mixar_card_button'):
        layout.mixar_card_button(kind=kind, active_default=default)


def _op_button(layout, operator_id, text, kind='CARD', default=False):
    props = layout.operator(operator_id, text=text)
    _style_last(layout, kind, default)
    return props


def _dismiss(layout, text, kind='GHOST', default=False):
    if hasattr(layout, 'template_popup_confirm'):
        layout.template_popup_confirm("", text="", cancel_text=text)
        _style_last(layout, kind, default)


def _section(layout):
    return layout.mixar_section() if hasattr(layout, 'mixar_section') else layout.box()


def _divider(layout):
    row = layout.row()
    row.scale_y = CARD_ROW_DIVIDER
    card_label(row, "", 'DIVIDER')


def draw_dialog(layout, wm):
    state = wm.mixar_referral_state
    if state == C.STATE_LOADING:
        card_label(layout, "Getting your invite link…", 'MUTED')
        _footer(layout, busy="Loading…")
        return
    if state == C.STATE_ERROR:
        card_label(layout, wm.mixar_referral_error or "Couldn't load your invite link",
                   'DANGER')
        row = layout.row(align=True)
        row.scale_y = CARD_ROW_CTA
        _dismiss(row, "Close")
        _op_button(row, OP_RELOAD, "Try Again", 'ACCENT', default=True)
        return

    _draw_pitch(layout, wm)
    _divider(layout)
    _draw_link(layout, wm)
    layout.separator(factor=0.6)
    _draw_emails(layout, wm)
    _footer(layout, busy="Sending…" if state == C.STATE_SENDING else "")


def _draw_pitch(layout, wm):
    invitee = wm.mixar_referral_invitee_award
    inviter = wm.mixar_referral_inviter_award
    paid = wm.mixar_referral_paid_total
    card_label(layout, "Out of credits? Invite friends and earn bonus credits.", 'SECTION')
    if invitee or inviter:
        card_label(layout, f"They get {format_credits(invitee)} credits and you get "
                           f"{format_credits(inviter)} after their first generation.",
                   'MUTED')
    if paid > inviter:
        card_label(layout, f"You earn {format_credits(paid)} in total if they subscribe.",
                   'MUTED')
    count = wm.mixar_referral_count
    if count:
        noun = "friend has" if count == 1 else "friends have"
        card_label(layout, f"{count} {noun} joined with your link so far.", 'META')


def _draw_link(layout, wm):
    box = _section(layout)
    col = box.column()
    card_label(col, "Your invite link", 'SECTION')
    row = col.row(align=True)
    row.scale_y = CARD_ROW_FIELD
    row.label(text=wm.mixar_referral_url)
    _op_button(row, OP_COPY, "Copy", 'CARD')


def _draw_emails(layout, wm):
    box = _section(layout)
    col = box.column()
    card_label(col, "Invite by email", 'SECTION')
    card_label(col, f"Up to {C.MAX_INVITES_PER_SEND} addresses, separated by commas. "
                    "We'll email them your link.", 'MUTED')
    row = col.row(align=True)
    row.scale_y = CARD_ROW_FIELD
    row.enabled = wm.mixar_referral_state == C.STATE_READY
    if hasattr(row, 'mixar_input'):
        row.mixar_input(wm, "mixar_referral_emails", text="")
    else:
        row.prop(wm, "mixar_referral_emails", text="")

    if wm.mixar_referral_notice:
        kind = 'DANGER' if wm.mixar_referral_notice_kind == C.NOTICE_ERROR else 'SECTION'
        card_label(col, wm.mixar_referral_notice, kind)
    for line in filter(None, wm.mixar_referral_details.split("\n")):
        card_label(col, line, 'MUTED')


def _footer(layout, busy=""):
    layout.separator(factor=0.9)
    row = layout.row(align=True)
    row.scale_y = CARD_ROW_CTA
    if busy:
        sub = row.row()
        sub.enabled = False
        # Disabled progress pill keeps the default flag (and so keeps the
        # native OK row suppressed) while the request runs.
        _op_button(sub, OP_SEND, busy, 'ACCENT', default=True)
        return
    _dismiss(row, "Done")
    _op_button(row, OP_SEND, "Send Invites", 'ACCENT', default=True)


# Auto-discovery imports every file under ui/ — nothing to register here.
classes = ()
