# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""AI Provider settings — the sidebar and the form (IDLE / SAVING / ERROR).

Sidebar: "PROVIDERS", one pill per catalog provider plus OpenRouter and
Codex, and the LOCAL MODEL foot. Right column: "ALL SUPPORTED <PROVIDER>
MODELS" as butted chips, the flexible area, the status lines, then the key
prompt, its note and the key field with Save & Activate docked inside it.
OpenRouter swaps the chips for its model-slug field, Codex's field is the
sign-in file path, Local draws `byok_local_ops.draw_local_fields`.

Status lines over the prompt, one per fact about the saved key:
- **key needed** — active for the account but not on this computer (or the
  dialog came from the chat's key-missing card): provider and model stay as
  saved (sidebar and chips locked), only the key is asked for;
- **in use** — with Remove key / Disconnect (Raj's two-step: CONFIRM_REMOVE);
- **paused** — the island picked Mixie; this computer still holds the key:
  Use my key / Forget;
- the error, wrapped.

Rows and chips are `mixar_byok.pick` buttons writing the same form
properties the save path reads. Geometry comes from `common/sheet/kit` (design
px); this module only decides what goes where.
"""

from mixar.modules.common.i18n import iface_, n_, rpt_

from ...constants import LOCAL_PROVIDER_ID
from ...core import catalog_labels, key_prompt, model_suggestions
from mixar.modules.common.sheet import kit as S

OP_PICK = "mixar_byok.pick"
OP_SAVE = "mixar_byok.save"
OP_USE_KEY = "mixar_byok.use_key"
OP_FORGET_KEY = "mixar_byok.forget_stored_key"
OP_REQUEST_REMOVE = "mixar_byok.request_remove"
# The in-app help link opens the BYOK section of the published docs
# (mixie-frontend src/pages/docsByok.ts, section id "your-own-provider").
BYOK_GUIDE_URL = "https://www.mixar.app/docs#your-own-provider"

# Design px a chip row may use: the right column less its inset and margin.
CHIP_ROW_WIDTH = S.WIDTH - S.RIGHT_X - S.RIGHT_INSET - S.RIGHT_MARGIN
ERROR_WRAP_CHARS = 80
# Room the Local branch's fields take inside the flexible area: its taller
# (Custom) branch — mode chips, detected apps, three labelled fields and the
# two closing notes (byok_local_ops.draw_local_fields).
LOCAL_FIELDS_HEIGHT = (S.CHIP_H + S.GAP + 4 * (S.NOTE_H + S.FIELD_H)
                       + S.GAP + 2 * S.NOTE_H)
STORED_NOTE = n_("Stored only on this computer, used only for Mixar agent requests - "
                 "Mixar never keeps a copy.")


def provider_label(provider_id):
    return catalog_labels.lookup_provider_label(provider_id)


def model_label(provider_id, model_id):
    return catalog_labels.lookup_model_label(provider_id, model_id)


def device_key_missing(wm) -> bool:
    """Active server-side, but this device holds no usable key (the server
    keeps metadata only — core/key_store). A dialog opened from the chat's
    key-missing card is in this state by definition (`core/key_prompt`)."""
    if key_prompt.is_open():
        return True
    return bool(wm.byok_is_active and getattr(wm, 'byok_device_key_missing', False))


def key_paused(wm) -> bool:
    """Inactive for the account, but this computer still holds the key the
    island's Mixie pick paused (`credential_state.byok_key_resumable`)."""
    return bool(not wm.byok_is_active and getattr(wm, 'byok_key_resumable', False))


def sidebar_providers():
    """Provider rows of the sidebar; Local is the foot, not a row."""
    return [item for item in model_suggestions.get_provider_items()
            if not model_suggestions.is_local(item[0])]


def sidebar_rows():
    """Rows the sidebar's height budget counts: the providers."""
    return len(sidebar_providers())


def signs_in(provider):
    """A provider used through a sign-in or a local server, not an API key."""
    return model_suggestions.is_codex(provider) or model_suggestions.is_local(provider)


def remove_text(provider):
    """The in-use strip's remove button: a key is removed, a sign-in disconnected."""
    return iface_("Disconnect") if signs_in(provider) else iface_("Remove key")


def _key_text(provider, preview):
    """What identifies the active key in the in-use strip. A Codex preview is
    "ChatGPT · <account>"; the strip keeps the account only."""
    if not preview:
        return "" if signs_in(provider) else iface_("key stored securely")
    if model_suggestions.is_codex(provider):
        return preview.rsplit(" · ", 1)[-1]
    return preview


def wrap(text, width):
    """Word-wrap for inline text (labels don't wrap on their own)."""
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


def _pill(line, operator_id, text, kind=S.SECONDARY):
    """A pill sized to its label, followed by the artboard's gap."""
    props = S.button(S.sized(line, S.text_width(line, kind, text) + S.BUTTON_PAD),
                     operator_id, text, kind)
    S.gap(line, S.GAP)
    return props


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def draw_sidebar(col, wm, geo, enabled):
    """The provider column: caption, pill rows, the Local Model foot."""
    body = S.fixed(col, geo.left_body)
    body.enabled = enabled
    S.sep(body, S.CAPTION_TOP)
    # The caption row carries the published guide at its right end, where the
    # provider plates stop, so it reads as the section's "how it works".
    head = S.row(body, S.CAPTION_H, left=S.LEFT_INSET, right=S.ROW_RIGHT)
    S.label(head, n_("PROVIDERS"), S.CAPTION)
    text = iface_("Guide")
    S.button(S.sized(head, S.text_width(head, S.SECONDARY, text) + S.BUTTON_PAD),
             "wm.url_open", text, S.SECONDARY).url = BYOK_GUIDE_URL
    S.sep(body, S.CAPTION_TO_ROWS)
    current = wm.byok_form_provider
    for pid, label, _desc in sidebar_providers():
        if pid == 'NONE':
            # Loading / empty sentinel: say so instead of offering a row.
            S.label(S.row(body, S.ROW_H, left=S.LEFT_INSET), label, S.NOTE)
            continue
        text = label
        S.choice(S.row(body, S.ROW_H, left=S.LEFT_INSET, right=S.row_right(body, text)),
                 OP_PICK, text, S.PROVIDER_ROW, lit=(pid == current), provider=pid)

    # Local model: a row like the providers at the column's foot (its glyph
    # drawn by the painter), not a full-width slab.
    foot = S.fixed(col, S.FOOTER)
    foot.enabled = enabled
    S.choice(S.row(foot, S.ROW_H, left=S.LEFT_INSET, right=S.ROW_RIGHT), OP_PICK,
             iface_("Local model"), S.FOOTER_ROW,
             lit=model_suggestions.is_local(current), provider=LOCAL_PROVIDER_ID)
    # The rest of the foot is margin under the row, off the card's edge.
    S.sep(foot, S.FOOTER - S.ROW_H)


# ---------------------------------------------------------------------------
# The form (right column)
# ---------------------------------------------------------------------------

class FormPlan:
    """What the right column needs for the geometry, and how to build it."""

    def __init__(self, layout, wm, state):
        self.wm = wm
        self.state = state
        self.provider = wm.byok_form_provider
        self.key_only = device_key_missing(wm)
        self.chips = []
        self.strips = self._plan_strips()
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
            notes = 2 * S.NOTE_H + S.GAP if self.kind == 'codex' else 0.0
            self.need = S.chips_height(len(self.chips)) + S.GAP + notes + strips_h
            self.bottom = S.key_block_height()

    def _plan_strips(self):
        wm, state = self.wm, self.state
        strips = []
        if state in ('IDLE', 'ERROR', 'SAVING'):
            if self.key_only:
                strips.append(('missing', None))
            elif wm.byok_is_active:
                strips.append(('in_use', None))
            elif key_paused(wm):
                strips.append(('paused', None))
        if state == 'ERROR' and wm.byok_last_error:
            # Static messages are stored as msgids; formatted ones arrive translated.
            strips += [('error', line) for line in
                       wrap(rpt_(wm.byok_last_error), ERROR_WRAP_CHARS)[:2]]
        return strips

    # -- build ---------------------------------------------------------------

    def build(self, col, geo):
        wm = self.wm
        S.sep(col, S.CAPTION_TOP)
        S.caption(col, self._caption(), S.RIGHT_INSET, translate=False)
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
            if self.kind == 'codex':
                self._codex_notes(area)
        self._strips(col)

        if self.kind == 'local':
            self._action_row(col, OP_SAVE, self._save_text())
        elif self.kind == 'openrouter':
            self._key_block(col, iface_("Enter your OpenRouter API key here."),
                            STORED_NOTE, 'byok_form_api_key', key_prompt.FOCUS_KEY)
        elif self.kind == 'codex':
            from . import byok_codex_ops
            note, _kind = byok_codex_ops.path_status(wm.byok_form_codex_path or "")
            # Short prompt; the hint under it names the file in use (empty
            # field = the default ~/.codex/auth.json, which path_status shows).
            self._key_block(col, iface_("Codex sign-in file"),
                            note, 'byok_form_codex_path', key_prompt.FOCUS_CODEX_PATH,
                            translate_note=False)
        else:
            self._key_block(col, iface_("Enter API key for {model} here.").format(
                model=model_label(self.provider, wm.byok_form_model)),
                STORED_NOTE, 'byok_form_api_key', key_prompt.FOCUS_KEY)

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
            # Key needed: provider and model stay as saved — only the key is asked.
            line.enabled = not self.key_only
            for mid, label, width in chips:
                S.choice(S.sized(line, width), OP_PICK, label, S.CHIP,
                         lit=(mid == current), model=mid)

    def _codex_notes(self, area):
        S.sep(area, S.GAP)
        for line in (n_("Run  codex login  in your terminal; Mixar uses that sign-in in place."),
                     n_("Uses your ChatGPT subscription - Mixar credits are not charged.")):
            S.label(S.row(area, S.NOTE_H, left=S.PROMPT_INSET), line, S.NOTE)

    def _openrouter_area(self, area):
        slug = S.row(area, S.FIELD_H, left=S.RIGHT_INSET, right=S.RIGHT_MARGIN)
        slug.enabled = not self.key_only
        S.input_field(slug, self.wm, 'byok_form_openrouter_model')
        S.sep(area, S.GAP)
        S.label(S.row(area, S.NOTE_H, left=S.PROMPT_INSET),
                n_("Any slug from openrouter.ai/models, e.g. anthropic/claude-opus-4.8."),
                S.NOTE)
        S.label(S.row(area, S.NOTE_H, left=S.PROMPT_INSET),
                n_("Pick a model that can use tools - the agent needs it. Most current "
                   "models can."), S.NOTE)

    def _strips(self, col):
        wm = self.wm
        for kind, line in self.strips:
            strip = S.row(col, S.STRIP_H, left=S.PROMPT_INSET, right=S.RIGHT_MARGIN)
            if kind == 'error':
                S.label(strip, line, S.DANGER_TEXT, translate=False)
                continue
            if kind == 'paused':
                from ...core import credential_state
                provider, model = credential_state.resume_target()
                key = ""
            else:
                provider, model = wm.byok_current_provider, wm.byok_current_model
                key = _key_text(provider, wm.byok_key_preview)
            values = dict(provider=provider_label(provider), model=model_label(provider, model),
                          key=key)
            if kind == 'missing':
                S.label(strip, iface_("Key needed on this computer: {provider} · {model}. "
                                      "Enter it below.").format(**values),
                        S.DANGER_TEXT, translate=False)
                continue
            if kind == 'in_use':
                # The caption and the lit sidebar row already name the shown provider.
                parts = [values['model'], key] if provider == self.provider else \
                    [values['provider'], values['model'], key]
                text = iface_("In use: {details}").format(
                    details=" · ".join(part for part in parts if part))
            else:
                text = iface_("Paused, Mixie is answering: {provider} · {model}").format(**values)
            S.label(strip, text, S.NOTE, translate=False)
            if self.state != 'IDLE':
                continue
            if kind == 'paused':
                _pill(strip, OP_USE_KEY, iface_("Use my key"))
                _pill(strip, OP_FORGET_KEY, iface_("Forget"), S.DANGER_BUTTON)
            else:
                _pill(strip, OP_REQUEST_REMOVE, remove_text(provider), S.DANGER_BUTTON)

    def _save_text(self):
        if self.state == 'SAVING':
            return iface_("Validating with your provider…")
        if self.state == 'ERROR':
            return iface_("Try Again")
        return iface_("Save & Activate")

    def _docked_save(self, field, prop, focus):
        """Save & Activate docked in ``field``: the artboard's SAVE_W pill, wider
        only when its label (Validating with your provider…) needs it."""
        text = self._save_text()
        width = max(S.SAVE_W, S.text_width(field, S.PRIMARY, text) + 2 * S.BUTTON_PAD)
        # A path field carries Blender's browse button (one UI unit) before
        # the Save pill; the field's backdrop runs under both.
        browse = S.UNIT_DP if prop == 'byok_form_codex_path' else 0.0
        S.input_field(field, self.wm, prop, docked_w=width + S.DOCK_INSET + browse,
                      activate=key_prompt.focus_is(focus))
        save = S.sized(field, width + S.DOCK_INSET)
        save.enabled = self.state != 'SAVING'
        S.button(save, OP_SAVE, text, S.PRIMARY, default=True, docked=True)

    def _key_block(self, col, prompt, note, prop, focus, translate_note=True):
        S.label(S.row(col, S.PROMPT_H, left=S.PROMPT_INSET), prompt, S.PROMPT, translate=False)
        S.label(S.row(col, S.NOTE_H, left=S.PROMPT_INSET), note, S.NOTE,
                translate=translate_note)
        S.sep(col, S.NOTE_TO_INPUT)
        field = S.row(col, S.INPUT_H, left=S.RIGHT_INSET, right=S.RIGHT_MARGIN)
        field.enabled = self.state != 'SAVING'
        self._docked_save(field, prop, focus)

    def _action_row(self, col, op, text):
        """A bare primary at the foot, right-aligned (no key field)."""
        S.sep(col, S.NOTE_TO_INPUT)
        line = S.row(col, S.INPUT_H, left=S.RIGHT_INSET, right=S.RIGHT_MARGIN, align='RIGHT')
        line.enabled = self.state != 'SAVING'
        width = max(S.SAVE_W, S.text_width(line, S.PRIMARY, text) + 2 * S.BUTTON_PAD)
        S.button(S.sized(line, width), op, text, S.PRIMARY, default=True)


classes = ()
