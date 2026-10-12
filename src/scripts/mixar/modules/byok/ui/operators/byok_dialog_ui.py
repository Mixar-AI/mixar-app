# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""AI Provider settings dialog — the sheet and its states.

One framed card for every state (the designer's artboard, see
`byok_sheet`): title and subtitle over the header divider, the provider
sidebar with its LOCAL MODEL foot, and a right column whose contents
follow ``wm.byok_dialog_state``:

  IDLE / ERROR / SAVING  the form (`byok_provider_settings_ui.FormPlan`)
  CONFIRM_REMOVE         the switch-back warning, Keep My Key / Remove
  REMOVING / SAVED / REMOVED   a recap with one Done (or a busy pill)

The one-action contract: every state marks exactly ONE button as the
dialog's active default (`byok_sheet.button(default=True)` /
`dismiss(default=True)`), which is what keeps the props dialog's automatic
OK/Cancel row away and gives Return one meaning. Dialog-closing buttons
(the ✕, Done) are ``template_popup_confirm`` cancel buttons, so closing
runs the operator's ``cancel()`` secret wipe exactly like Esc.

State machine lives on WindowManager (see ui/properties/byok_props.py);
operators and async flow live in byok_ops.py. This module only draws.
"""

from mixar.modules.common.i18n import iface_, n_

from ...core import catalog_labels, model_suggestions
from . import byok_provider_settings_ui as form
from . import byok_sheet as S

# Operator idnames as literals — byok_ops imports this module for its
# draw() body, so importing the classes back would be circular.
OP_SAVE = form.OP_SAVE
OP_REQUEST_REMOVE = form.OP_REQUEST_REMOVE
OP_CANCEL_REMOVE = "mixar_byok.cancel_remove"
OP_CONFIRM_REMOVE = "mixar_byok.confirm_remove"
OP_CODEX_LOAD_FILE = form.OP_CODEX_LOAD_FILE
OP_CODEX_PASTE = form.OP_CODEX_PASTE

# Header close button: the painter draws a cross; the label is for the
# QA dump and the stock-widget fallback.
CLOSE_GLYPH = S.CLOSE_GLYPH

BUSY_STATES = ('SAVING', 'REMOVING')
BODY_ROW = 40

lookup_provider_label = catalog_labels.lookup_provider_label
lookup_model_label = catalog_labels.lookup_model_label


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def draw_dialog(layout, wm):
    """Entry point — byok_ops.MIXAR_BYOK_OT_open_dialog.draw() delegates here."""
    layout.use_property_split = False
    layout.use_property_decorate = False
    state = wm.byok_dialog_state

    sheet = layout.column(align=True)
    if hasattr(sheet, 'mixar_sheet_frame'):
        sheet.mixar_sheet_frame(header=S.HEADER, sidebar=S.SIDEBAR)
    _draw_header(sheet, state)

    plan = _plan(sheet, wm, state)
    geo = S.Geometry(len(form.sidebar_providers()), plan.need, plan.bottom)
    body = sheet.split(factor=S.SPLIT_FACTOR, align=True)
    form.draw_sidebar(body.column(align=True), wm, geo, enabled=state in ('IDLE', 'ERROR'))
    plan.build(S.fixed(body.column(align=True), geo.right), geo)


def _plan(layout, wm, state):
    if state == 'CONFIRM_REMOVE':
        return _ConfirmPlan(wm, removing=False)
    if state == 'REMOVING':
        return _ConfirmPlan(wm, removing=True)
    if state == 'SAVED':
        return _RecapPlan(wm, saved=True)
    if state == 'REMOVED':
        return _RecapPlan(wm, saved=False)
    return form.FormPlan(layout, wm, state)


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

def _draw_header(sheet, state):
    header = sheet.row(align=True)
    title = header.row(align=True)
    title.scale_y = S.units(S.HEADER)
    S.label(title,
            iface_("AI Provider settings") + "\n"
            + iface_("Use Mixar with your own provider - You won't be charged on Mixar credits."),
            S.TITLE, translate=False)
    if state in BUSY_STATES:
        # Busy states keep the dialog until the request lands.
        return
    # The ✕: a cancel-path dismiss, so Esc and this both wipe transient
    # secrets. A 100-wide slot, 42 from the right, reaching down from the
    # sheet's top edge; the painter puts the 100-square at its foot, 40
    # below the edge (the slot's top is the sheet's top margin).
    slot = S.sized(header, S.CLOSE)
    slot.scale_y = S.units(S.CLOSE_TOP + S.CLOSE)
    S.dismiss(slot, CLOSE_GLYPH, S.CLOSE_KIND)
    S.gap(header, S.CLOSE_RIGHT)


# ---------------------------------------------------------------------------
# Confirm / recap states (right column)
# ---------------------------------------------------------------------------

def _config_lines(wm):
    provider = wm.byok_current_provider
    lines = [
        iface_("Provider: {provider}").format(provider=lookup_provider_label(provider)),
        iface_("Model: {model}").format(model=lookup_model_label(provider, wm.byok_current_model)),
    ]
    if model_suggestions.is_codex(provider):
        lines.append(iface_("Account: {account}").format(
            account=wm.byok_key_preview or iface_("ChatGPT subscription")))
    else:
        lines.append(iface_("API key: {key}").format(
            key=wm.byok_key_preview or iface_("stored securely")))
    if not wm.byok_current_supports_vision:
        lines.append(iface_("Text-only model - chat works; 3D tasks run without visual feedback."))
    return lines


def _lines(area, lines, kind=S.BODY):
    for line in lines:
        S.label(S.row(area, BODY_ROW, left=S.RIGHT_INSET), line, kind, translate=False)


def _pill_width(layout, kind, text):
    return S.text_width(layout, kind, text) + 2 * S.BUTTON_PAD


class _ConfirmPlan:
    """CONFIRM_REMOVE (Keep My Key is the safe default) and REMOVING."""

    need = 7 * BODY_ROW + S.GAP
    bottom = S.action_block_height()

    def __init__(self, wm, removing):
        self.wm = wm
        self.removing = removing

    def build(self, col, geo):
        S.sep(col, S.CAPTION_TOP)
        S.caption(col, n_("SWITCH BACK TO MIXIE?"), S.RIGHT_INSET)
        S.sep(col, S.CAPTION_TO_CHIPS)
        area = S.fixed(col, geo.area)
        _lines(area, _config_lines(self.wm))
        S.sep(area, S.GAP)
        _lines(area, [
            iface_("This removes your saved API key; the agent runs on Mixie again."),
            iface_("Mixar credits will be charged for future agent requests."),
        ], S.NOTE)
        S.sep(col, S.NOTE_TO_INPUT)
        line = S.row(col, S.INPUT_H, left=S.RIGHT_INSET, right=S.RIGHT_MARGIN, align='RIGHT')
        if self.removing:
            busy = S.sized(line, S.SAVE_W)
            busy.enabled = False
            # A disabled pill keeps the primary slot (and the active-default
            # flag) while the delete is in flight; Return does nothing on it.
            S.button(busy, OP_SAVE, iface_("Removing your key…"), S.PRIMARY, default=True)
            return
        keep = iface_("Keep My Key")
        S.button(S.sized(line, _pill_width(line, S.SECONDARY, keep)), OP_CANCEL_REMOVE, keep,
                 S.SECONDARY, default=True)
        S.gap(line, S.GAP)
        remove = iface_("Remove API Key")
        S.button(S.sized(line, _pill_width(line, S.DANGER_BUTTON, remove)), OP_CONFIRM_REMOVE,
                 remove, S.DANGER_BUTTON)


class _RecapPlan:
    """SAVED / REMOVED: the explicit "it landed" moment with one Done."""

    need = 6 * BODY_ROW + S.GAP
    bottom = S.action_block_height()

    def __init__(self, wm, saved):
        self.wm = wm
        self.saved = saved

    def build(self, col, geo):
        S.sep(col, S.CAPTION_TOP)
        S.caption(col, n_("SAVED") if self.saved else n_("API KEY REMOVED"), S.RIGHT_INSET)
        S.sep(col, S.CAPTION_TO_CHIPS)
        area = S.fixed(col, geo.area)
        if self.saved:
            _lines(area, [iface_("The Mixar agent now runs on your provider - "
                                 "Mixar credits are not charged.")])
            S.sep(area, S.GAP)
            _lines(area, _config_lines(self.wm), S.NOTE)
        else:
            _lines(area, [iface_("The agent is back on Mixie, Mixar's hosted models.")])
            _lines(area, [iface_("Mixar credits are charged for agent requests again.")], S.NOTE)
        S.sep(col, S.NOTE_TO_INPUT)
        line = S.row(col, S.INPUT_H, left=S.RIGHT_INSET, right=S.RIGHT_MARGIN, align='RIGHT')
        S.dismiss(S.sized(line, S.SAVE_W), iface_(S.DONE_TEXT), S.PRIMARY, default=True)


# Auto-discovery imports every file under ui/ — nothing to register here.
classes = ()
