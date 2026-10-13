# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""AI Provider settings — the sidebar and the form (IDLE / SAVING / ERROR).

Sidebar: "PROVIDERS", one pill row per catalog provider plus OpenRouter and
Codex, and the LOCAL MODEL foot. Right column: "ALL SUPPORTED <PROVIDER>
MODELS" as butted chips, the flexible area, then the key prompt, its note
and the key field with Save & Activate docked inside it. OpenRouter swaps
the chips for its model-slug field, Codex adds the auth.json load/paste
row, Local draws `byok_local_ops.draw_local_fields`.

Rows and chips are `mixar_byok.pick` buttons writing the same form
properties the save path reads. Geometry comes from `byok_sheet` (design
px); this module only decides what goes where. The recap and confirm
states live in `byok_dialog_ui`.
"""

from mixar.modules.common.i18n import iface_, n_

from ...constants import LOCAL_PROVIDER_ID
from ...core import catalog_labels, model_suggestions
from . import byok_sheet as S

OP_PICK = "mixar_byok.pick"
OP_SAVE = "mixar_byok.save"
OP_REQUEST_REMOVE = "mixar_byok.request_remove"
OP_CODEX_LOAD_FILE = "mixar_byok.codex_load_file"
OP_CODEX_PASTE = "mixar_byok.codex_paste"

# Design px a chip row may use: the right column less its inset and margin.
CHIP_ROW_WIDTH = S.WIDTH - S.RIGHT_X - S.RIGHT_INSET - S.RIGHT_MARGIN
ERROR_WRAP_CHARS = 80
# Room the Local branch's fields take inside the flexible area.
LOCAL_FIELDS_HEIGHT = 440
STORED_NOTE = n_("Stored encrypted, used only for Mixar agent requests - "
                 "only a masked preview is shown after saving.")


def sidebar_providers():
    """Provider rows of the sidebar; Local is the foot, not a row."""
    return [item for item in model_suggestions.get_provider_items()
            if not model_suggestions.is_local(item[0])]


def provider_label(provider_id):
    return catalog_labels.lookup_provider_label(provider_id)


def model_label(provider_id, model_id):
    return catalog_labels.lookup_model_label(provider_id, model_id)


def _wrap(text, width):
    """Word-wrap for inline error text (labels don't wrap on their own)."""
    lines, current = [], ""
    for word in text.split():
        if len(current) + len(word) + 1 > width and current:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def draw_sidebar(col, wm, geo, enabled):
    """The provider column: caption, pill rows, the Local Model foot."""
    body = S.fixed(col, geo.left_body)
    body.enabled = enabled
    S.sep(body, S.CAPTION_TOP)
    S.caption(body, n_("PROVIDERS"), S.LEFT_INSET)
    S.sep(body, S.CAPTION_TO_ROWS)
    current = wm.byok_form_provider
    for pid, label, _desc in sidebar_providers():
        if pid == 'NONE':
            # Loading / empty sentinel: say so instead of offering a row.
            S.label(S.row(body, S.ROW_H, left=S.LEFT_INSET), label, S.NOTE)
            continue
        text = label.upper()
        S.choice(S.row(body, S.ROW_H, left=S.LEFT_INSET, right=S.row_right(body, text)),
                 OP_PICK, text, S.PROVIDER_ROW, lit=(pid == current), provider=pid)

    foot = col.row(align=True)
    foot.scale_y = S.units(S.FOOTER)
    foot.enabled = enabled
    S.choice(foot, OP_PICK, iface_("LOCAL MODEL"), S.FOOTER_ROW,
             lit=model_suggestions.is_local(current), provider=LOCAL_PROVIDER_ID)


# ---------------------------------------------------------------------------
# The form (right column)
# ---------------------------------------------------------------------------

class FormPlan:
    """What the right column needs for the geometry, and how to build it."""

    def __init__(self, layout, wm, state):
        self.wm = wm
        self.state = state
        self.provider = wm.byok_form_provider
        self.chips = []
        # Lines directly above the key prompt: the key in use, then the error.
        # A failed save or remove never touches the stored key, so the key in
        # use stays named in ERROR too (its Remove button only in IDLE).
        self.strips = []
        if wm.byok_is_active and state in ('IDLE', 'ERROR'):
            self.strips.append(('in_use', None))
        if state == 'ERROR' and wm.byok_last_error:
            self.strips += [('error', line) for line in
                            _wrap(iface_(wm.byok_last_error), ERROR_WRAP_CHARS)[:2]]
        strips_h = len(self.strips) * S.STRIP_H

        if model_suggestions.is_local(self.provider):
            self.kind = 'local'
            self.need = LOCAL_FIELDS_HEIGHT + strips_h
            self.bottom = S.action_block_height()
        elif model_suggestions.is_openrouter(self.provider):
            self.kind = 'openrouter'
            self.need = S.FIELD_H + S.GAP + 2 * S.NOTE_H + S.GAP + strips_h
            self.bottom = S.key_block_height()
        elif self.provider == 'NONE':
            self.kind = 'none'
            self.need = S.NOTE_H + strips_h
            self.bottom = S.key_block_height()
        else:
            self.kind = 'codex' if model_suggestions.is_codex(self.provider) else 'cloud'
            items = [(mid, label) for mid, label, _desc in
                     model_suggestions.get_model_items(self.provider) if mid != 'NONE']
            self.chips = S.chip_rows(layout, items, CHIP_ROW_WIDTH)
            self.need = S.chips_height(len(self.chips)) + S.GAP + strips_h
            self.bottom = S.key_block_height(
                S.GAP + S.BUTTON_H if self.kind == 'codex' else 0.0)

    # -- build ---------------------------------------------------------------

    def build(self, col, geo):
        wm = self.wm
        S.sep(col, S.CAPTION_TOP)
        S.caption(col, self._caption(), S.RIGHT_INSET)
        S.sep(col, S.CAPTION_TO_CHIPS)
        area = S.fixed(col, geo.area - len(self.strips) * S.STRIP_H)
        area.enabled = self.state != 'SAVING'
        if self.kind == 'local':
            from . import byok_local_ops
            byok_local_ops.draw_local_fields(area, wm)
        elif self.kind == 'openrouter':
            self._openrouter_area(area)
        elif self.kind == 'none':
            S.label(S.row(area, S.NOTE_H, left=S.RIGHT_INSET),
                    n_("Pick a provider on the left to see its models."), S.NOTE)
        else:
            self._chips(area)
        self._strips(col)

        if self.kind == 'local':
            self._action_row(col, OP_SAVE, self._save_text())
        elif self.kind == 'openrouter':
            self._key_block(col, iface_("Enter your OpenRouter API key here."),
                            'byok_form_api_key')
        elif self.kind == 'codex':
            self._codex_block(col)
        else:
            self._key_block(col, iface_("Enter API key for {model} here.").format(
                model=model_label(self.provider, wm.byok_form_model)), 'byok_form_api_key')

    def _caption(self):
        if self.kind == 'local':
            return iface_("LOCAL MODEL ON THIS COMPUTER")
        if self.kind == 'openrouter':
            return iface_("ANY OPENROUTER MODEL")
        if self.kind == 'none':
            return iface_("MODELS")
        return iface_("ALL SUPPORTED {provider} MODELS").format(
            provider=S.bright(provider_label(self.provider).upper()))

    def _chips(self, area):
        if not self.chips:
            S.label(S.row(area, S.NOTE_H, left=S.RIGHT_INSET),
                    n_("No models available for this provider yet."), S.NOTE)
            return
        current = self.wm.byok_form_model
        for index, chips in enumerate(self.chips):
            if index:
                S.sep(area, S.CHIP_GAP_Y)
            line = S.row(area, S.CHIP_H, left=S.RIGHT_INSET, packed=True)
            for mid, label, width in chips:
                S.choice(S.sized(line, width), OP_PICK, label, S.CHIP,
                         lit=(mid == current), model=mid)

    def _openrouter_area(self, area):
        S.input_field(S.row(area, S.FIELD_H, left=S.RIGHT_INSET, right=S.RIGHT_MARGIN),
                      self.wm, 'byok_form_openrouter_model')
        S.sep(area, S.GAP)
        S.label(S.row(area, S.NOTE_H, left=S.PROMPT_INSET),
                n_("Any slug from openrouter.ai/models, e.g. anthropic/claude-opus-4.8."),
                S.NOTE)
        S.label(S.row(area, S.NOTE_H, left=S.PROMPT_INSET),
                n_("Pick a model that supports tool / function calling - the agent needs it."),
                S.NOTE)

    def _strips(self, col):
        wm = self.wm
        for kind, line in self.strips:
            strip = S.row(col, S.STRIP_H, left=S.PROMPT_INSET, right=S.RIGHT_MARGIN)
            if kind == 'error':
                S.label(strip, line, S.DANGER_TEXT, translate=False)
                continue
            S.label(strip, iface_("In use: {provider} · {model} · {key}").format(
                provider=provider_label(wm.byok_current_provider),
                model=model_label(wm.byok_current_provider, wm.byok_current_model),
                key=wm.byok_key_preview or iface_("key stored securely"),
            ), S.NOTE, translate=False)
            if self.state != 'IDLE':
                continue
            text = iface_("Remove API Key…")
            width = S.text_width(strip, S.DANGER_BUTTON, text) + S.BUTTON_PAD
            S.button(S.sized(strip, width), OP_REQUEST_REMOVE, text, S.DANGER_BUTTON)

    def _save_text(self):
        if self.state == 'SAVING':
            return iface_("Validating with provider…")
        if self.state == 'ERROR':
            return iface_("Try Again")
        return iface_("Save & Activate")

    def _docked_save(self, field):
        """Save & Activate docked in ``field``: the artboard's 262 pill, wider
        only when its label (Validating with provider…) needs it."""
        text = self._save_text()
        width = max(S.SAVE_W, S.text_width(field, S.PRIMARY, text) + 2 * S.BUTTON_PAD)
        S.input_field(field, self.wm, self._field_prop, docked_w=width + S.DOCK_INSET)
        save = S.sized(field, width + S.DOCK_INSET)
        save.enabled = self.state != 'SAVING'
        S.button(save, OP_SAVE, text, S.PRIMARY, default=True, docked=True)

    def _key_block(self, col, prompt, prop):
        S.label(S.row(col, S.PROMPT_H, left=S.PROMPT_INSET), prompt, S.PROMPT, translate=False)
        S.label(S.row(col, S.NOTE_H, left=S.PROMPT_INSET), STORED_NOTE, S.NOTE)
        S.sep(col, S.NOTE_TO_INPUT)
        field = S.row(col, S.INPUT_H, left=S.RIGHT_INSET, right=S.RIGHT_MARGIN)
        field.enabled = self.state != 'SAVING'
        self._field_prop = prop
        self._docked_save(field)

    def _codex_block(self, col):
        wm = self.wm
        S.label(S.row(col, S.PROMPT_H, left=S.PROMPT_INSET),
                n_("Connect your ChatGPT subscription."), S.PROMPT)
        n = len(wm.byok_form_codex_bundle or "")
        S.label(S.row(col, S.NOTE_H, left=S.PROMPT_INSET),
                iface_("{count} characters loaded - Save & Activate sends them to Mixar.").format(count=n)
                if n else
                n_("Run  codex login  in a terminal, then load or paste ~/.codex/auth.json."),
                S.NOTE, translate=not n)
        S.sep(col, S.GAP)
        actions = S.row(col, S.BUTTON_H, left=S.RIGHT_INSET, packed=True)
        for op, text in ((OP_CODEX_LOAD_FILE, iface_("Load from ~/.codex/auth.json")),
                         (OP_CODEX_PASTE, iface_("Paste from clipboard"))):
            width = S.text_width(actions, S.SECONDARY, text) + 2 * S.BUTTON_PAD
            S.button(S.sized(actions, width), op, text, S.SECONDARY)
            S.gap(actions, S.GAP)
        S.sep(col, S.NOTE_TO_INPUT)
        field = S.row(col, S.INPUT_H, left=S.RIGHT_INSET, right=S.RIGHT_MARGIN)
        field.enabled = self.state != 'SAVING'
        self._field_prop = 'byok_form_codex_bundle'
        self._docked_save(field)

    def _action_row(self, col, op, text):
        """A bare primary at the foot, right-aligned (no key field)."""
        S.sep(col, S.NOTE_TO_INPUT)
        line = S.row(col, S.INPUT_H, left=S.RIGHT_INSET, right=S.RIGHT_MARGIN, align='RIGHT')
        line.enabled = self.state != 'SAVING'
        width = max(S.SAVE_W, S.text_width(line, S.PRIMARY, text) + 2 * S.BUTTON_PAD)
        S.button(S.sized(line, width), op, text, S.PRIMARY, default=True)


classes = ()
