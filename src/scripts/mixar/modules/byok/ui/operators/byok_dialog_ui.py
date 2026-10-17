# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""AI Provider settings dialog — the sheet and its states.

One framed card for every state (the designer's artboard, see
`common/sheet/kit`): title and subtitle over the header divider, the provider
sidebar with its LOCAL MODEL foot, and a right column whose contents follow
``wm.byok_dialog_state``:

  IDLE / ERROR / SAVING  the form (`byok_provider_settings_ui.FormPlan`)
  CONFIRM_REMOVE         the key, what removing it means, Keep / Remove
  REMOVING               the key and a busy pill until the DELETE lands
  SAVED / REMOVED        a recap with one Done

The one-action contract: every state marks exactly ONE button as the
dialog's active default (`kit.button(default=True)` /
`dismiss(default=True)`), which keeps the props dialog's automatic
OK/Cancel row away and gives Return one meaning. Dialog-closing buttons (the
✕, Done) are ``template_popup_confirm`` cancel buttons, so closing runs the
operator's ``cancel()`` secret wipe exactly like Esc.

State machine lives on WindowManager (see ui/properties/byok_props.py);
operators and async flow live in byok_ops.py. This module only draws.
"""

from mixar.modules.common.i18n import iface_, n_, rpt_

from ...core import catalog_labels, model_suggestions
from . import byok_provider_settings_ui as form
from mixar.modules.common.sheet import kit as S

# Operator idnames as literals — byok_ops imports this module for its draw()
# body, so importing the classes back would be circular.
OP_SAVE = form.OP_SAVE
OP_USE_KEY = form.OP_USE_KEY
OP_FORGET_KEY = form.OP_FORGET_KEY
OP_REQUEST_REMOVE = form.OP_REQUEST_REMOVE
OP_CANCEL_REMOVE = "mixar_byok.cancel_remove"
OP_CONFIRM_REMOVE = "mixar_byok.confirm_remove"

# The sheet's width in UI px (the artboard is a 2x export).
SHEET_WIDTH = S.WIDTH // 2
CLOSE_GLYPH = S.CLOSE_GLYPH
BUSY_STATES = ('SAVING', 'REMOVING')
BODY_ROW = 40

BYOK_GUIDE_URL = form.BYOK_GUIDE_URL

lookup_provider_label = catalog_labels.lookup_provider_label
lookup_model_label = catalog_labels.lookup_model_label
_device_key_missing = form.device_key_missing
_key_paused = form.key_paused


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
    geo = S.Geometry(form.sidebar_rows(), plan.need, plan.bottom)
    body = sheet.split(factor=S.SPLIT_FACTOR, align=True)
    form.draw_sidebar(body.column(align=True), wm, geo,
                      enabled=state in ('IDLE', 'ERROR') and not form.device_key_missing(wm))
    plan.build(S.fixed(body.column(align=True), geo.right), geo)


def _plan(layout, wm, state):
    if state == 'CONFIRM_REMOVE':
        return _ConfirmRemovePlan(wm)
    if state == 'REMOVING':
        return _RemovingPlan(wm)
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
            + iface_("Use Mixar with your own provider - you won't be charged Mixar credits."),
            S.TITLE, translate=False)
    if state in BUSY_STATES:
        # Busy states keep the dialog until the request lands.
        return
    # The ✕: a cancel-path dismiss, so Esc and this both wipe transient
    # secrets. A CLOSE-wide slot, CLOSE_RIGHT from the right, reaching down
    # from the sheet's top edge; the painter puts the CLOSE square at its
    # foot, CLOSE_TOP below the edge (the slot's top is the sheet's top).
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


def _hosted_ok(wm):
    """Mixar's own models need an account (not a guest, not signed out)."""
    return (bool(getattr(wm, 'mixie_chat_is_logged_in', True))
            and not getattr(wm, 'mixie_chat_is_guest', False))


def _lines(area, lines, kind=S.BODY):
    for line in lines:
        S.label(S.row(area, BODY_ROW, left=S.RIGHT_INSET), line, kind, translate=False)


def _foot_row(col):
    """The right column's foot, where the key field sits in the form."""
    S.sep(col, S.NOTE_TO_INPUT)
    return S.row(col, S.INPUT_H, left=S.RIGHT_INSET, right=S.RIGHT_MARGIN, align='RIGHT')


class _ConfirmRemovePlan:
    """CONFIRM_REMOVE: what removing the key means; keeping it is the default.
    A failed DELETE lands back here with its error over the buttons, so
    Remove is the retry."""

    bottom = S.action_block_height()

    def __init__(self, wm):
        self.wm = wm
        # Static messages are stored as msgids; formatted ones arrive translated.
        self.errors = form.wrap(rpt_(wm.byok_last_error), form.ERROR_WRAP_CHARS)[:2] \
            if wm.byok_last_error else []
        self.need = (7 + len(self.errors)) * BODY_ROW + S.GAP

    def build(self, col, geo):
        S.sep(col, S.CAPTION_TOP)
        signs_in = form.signs_in(self.wm.byok_current_provider)
        S.caption(col, n_("DISCONNECT THIS SIGN-IN?") if signs_in
                  else n_("REMOVE YOUR API KEY?"), S.RIGHT_INSET)
        S.sep(col, S.CAPTION_TO_CHIPS)
        area = S.fixed(col, geo.area)
        _lines(area, _config_lines(self.wm))
        S.sep(area, S.GAP)
        if _hosted_ok(self.wm):
            after = [iface_("The agent will use Mixar's models again."),
                     iface_("Agent chats will use Mixar credits again.")]
        else:
            # A guest (or signed out) has no Mixar models to fall back on.
            after = [iface_("The agent stops answering until you add a key again."),
                     iface_("Sign in to use Mixar models instead.")]
        _lines(area, after, S.NOTE)
        _lines(area, self.errors, S.DANGER_TEXT)
        line = _foot_row(col)
        keep = iface_("Stay connected") if signs_in else iface_("Keep my key")
        for op, text, kind, default in ((OP_CANCEL_REMOVE, keep, S.SECONDARY, True),
                                        (OP_CONFIRM_REMOVE, form.remove_text(self.wm.byok_current_provider),
                                         S.DANGER_BUTTON, False)):
            width = max(S.SAVE_W * 0.7, S.text_width(line, kind, text) + 2 * S.BUTTON_PAD)
            S.button(S.sized(line, width), op, text, kind, default=default)
            S.gap(line, S.GAP)


class _RemovingPlan:
    """REMOVING: the key being deleted and a busy pill until the DELETE lands."""

    need = 7 * BODY_ROW + S.GAP
    bottom = S.action_block_height()

    def __init__(self, wm):
        self.wm = wm

    def build(self, col, geo):
        S.sep(col, S.CAPTION_TOP)
        signs_in = form.signs_in(self.wm.byok_current_provider)
        S.caption(col, n_("DISCONNECTING") if signs_in else n_("REMOVING YOUR API KEY"),
                  S.RIGHT_INSET)
        S.sep(col, S.CAPTION_TO_CHIPS)
        area = S.fixed(col, geo.area)
        _lines(area, _config_lines(self.wm))
        busy = S.sized(_foot_row(col), S.SAVE_W)
        busy.enabled = False
        # A disabled pill keeps the primary slot (and the active-default flag)
        # while the delete is in flight; Return does nothing on it.
        S.button(busy, OP_SAVE, iface_("Disconnecting…") if signs_in
                 else iface_("Removing your key…"), S.PRIMARY, default=True)


class _RecapPlan:
    """SAVED / REMOVED: the explicit "it landed" moment with one Done."""

    need = 6 * BODY_ROW + S.GAP
    bottom = S.action_block_height()

    def __init__(self, wm, saved):
        self.wm = wm
        self.saved = saved

    def build(self, col, geo):
        S.sep(col, S.CAPTION_TOP)
        S.caption(col, n_("SAVED") if self.saved else n_("REMOVED"), S.RIGHT_INSET)
        S.sep(col, S.CAPTION_TO_CHIPS)
        area = S.fixed(col, geo.area)
        if self.saved:
            _lines(area, [iface_("You are set. Agent chats now run on your own provider.")])
            S.sep(area, S.GAP)
            _lines(area, _config_lines(self.wm), S.NOTE)
        elif _hosted_ok(self.wm):
            _lines(area, [iface_("The agent uses Mixar's models again.")])
            _lines(area, [iface_("Agent chats use Mixar credits again.")], S.NOTE)
        else:
            _lines(area, [iface_("Add a key to talk to the agent again.")])
            _lines(area, [iface_("Sign in to use Mixar models instead.")], S.NOTE)
        S.dismiss(S.sized(_foot_row(col), S.SAVE_W), iface_(S.DONE_TEXT), S.PRIMARY,
                  default=True)


# Auto-discovery imports every file under ui/ — nothing to register here.
classes = ()
