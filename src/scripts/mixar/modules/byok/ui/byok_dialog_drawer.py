# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layout and presentation logic for the BYOK dialog.

Split out of ``ui/operators/byok_ops.py`` so the operator module keeps to
control flow and this one owns everything the dialog puts on screen.

The dialog is one continuous surface across all four states. Rather than
swapping the body out per state, every state renders the same three bands
— status, form, footer — and only the footer's contents change. That keeps
the dialog from resizing under the cursor while an async save runs.

Everything above ``draw_dialog`` is a pure function of the WindowManager
state: no ``bpy`` calls, no layout objects. Panel ``draw()`` can't run
outside a GUI session, so keeping the decisions (what blocks Save, what
the status line says) separable is what makes them testable at all.
"""

from __future__ import annotations

from ..core import model_suggestions

# The masked key preview and provider labels can be long; wrap error text
# to roughly the dialog's usable character width.
ERROR_WRAP_WIDTH = 68


# ---------------------------------------------------------------------------
# Pure presentation logic
# ---------------------------------------------------------------------------

def lookup_provider_label(provider_id: str) -> str:
    """Resolve a provider ID to its human-readable label from the cache."""
    for pid, plabel, _desc in model_suggestions.get_provider_items():
        if pid == provider_id:
            return plabel
    return provider_id


def lookup_model_label(provider_id: str, model_id: str) -> str:
    """Resolve a model ID to its label, falling back to the raw ID.

    The fallback matters when an admin removes a model after the user
    saved it — the dialog should still name what is actually in use.
    """
    for mid, mlabel, _desc in model_suggestions.get_model_items(provider_id):
        if mid == model_id:
            return mlabel
    return model_id


def save_blocker(wm) -> str | None:
    """Return why Save is unavailable, or None when the form is complete.

    This is the single source of truth for both the Save operator's
    ``poll()`` and the hint shown beside the greyed-out button — a
    disabled control with no stated reason is the dialog's worst seam.

    Deliberately covers *requirements only*. The transient SAVING state
    also blocks the button, but it isn't something the user can fix, so
    it must not surface here as a requirement.
    """
    provider = getattr(wm, 'byok_form_provider', '') or ''

    if model_suggestions.is_openrouter(provider):
        if not (getattr(wm, 'byok_form_openrouter_model', '') or '').strip():
            return "Enter a model slug to continue."
        if not (getattr(wm, 'byok_form_api_key', '') or '').strip():
            return "Enter your API key to continue."
        return None

    if model_suggestions.is_codex(provider):
        if not (getattr(wm, 'byok_form_codex_model', '') or '').strip():
            return "Enter a model slug to continue."
        if not (getattr(wm, 'byok_form_codex_bundle', '') or '').strip():
            return "Load or paste your auth.json to continue."
        return None

    if not provider or provider == 'NONE':
        return "Choose a provider to continue."
    if not model_suggestions.is_valid_model(
        provider, getattr(wm, 'byok_form_model', '') or ''
    ):
        return "Choose a model for this provider."
    if not (getattr(wm, 'byok_form_api_key', '') or '').strip():
        return "Enter your API key to continue."
    return None


def status_summary(wm) -> str:
    """One-line description of what the agent is currently using.

    Replaces the old "Current configuration" box, which restated the
    provider and model that the form below it was already prefilled
    with. The masked key preview is the one part that appears nowhere
    else, so it stays.
    """
    if not getattr(wm, 'byok_is_active', False):
        return "Not configured — the agent uses Mixar's default provider."

    provider = getattr(wm, 'byok_current_provider', '') or ''
    model = getattr(wm, 'byok_current_model', '') or ''
    parts = [lookup_provider_label(provider), lookup_model_label(provider, model)]

    preview = getattr(wm, 'byok_key_preview', '') or ''
    if model_suggestions.is_codex(provider):
        parts.append(preview or "ChatGPT subscription")
    else:
        parts.append(preview or "Key stored securely")

    return "  ·  ".join(part for part in parts if part)


def codex_bundle_status(bundle: str) -> tuple[str, str]:
    """Text + icon confirming a pasted auth.json landed.

    The field is PASSWORD-masked, so this character count is the only
    feedback that the paste or file load actually took.
    """
    count = len(bundle or "")
    if count:
        return f"{count} characters loaded", 'CHECKMARK'
    return "Empty — load or paste your auth.json", 'INFO'


def wrap(text: str, width: int) -> list[str]:
    """Dumb word-wrap for error rendering (Blender labels don't wrap)."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        if len(current) + len(word) + 1 > width:
            if current:
                lines.append(current)
            current = word if len(word) <= width else word[:width]
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines or [""]


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def draw_dialog(layout, wm) -> None:
    """Render the whole dialog body for the current state."""
    state = wm.byok_dialog_state
    removing = state == 'CONFIRM_REMOVE'
    # The form is inert while an async save runs and while the remove
    # confirmation is up, but it stays on screen in both — hiding it would
    # reflow the dialog and drop the user's context mid-decision.
    frozen = removing or state == 'SAVING'

    _draw_status(layout, wm)
    layout.separator(factor=0.8)
    _draw_form(layout, wm, disabled=frozen)

    if state == 'ERROR' and wm.byok_last_error:
        _draw_error(layout, wm)

    layout.separator(factor=0.9)
    if removing:
        _draw_remove_confirm(layout)
    else:
        _draw_actions(layout, wm, saving=(state == 'SAVING'))


def _draw_status(layout, wm):
    """Status band: what's active now, plus any caveat about it.

    Stays visible in every state, including ERROR. A failed *re-save*
    does not delete the stored key, so hiding this would tell the user
    their working configuration had vanished when it hadn't.
    """
    row = layout.row(align=True)
    if wm.byok_is_active:
        row.label(text="Active", icon='KEY_HLT')
    else:
        row.label(text="Not configured", icon='UNLOCKED')

    detail = layout.row(align=True)
    detail.active = False
    detail.label(text=status_summary(wm), icon='BLANK1')

    # Text-only model: chat works, but 3D tasks run without the viewport
    # visual-feedback loop because images can't be sent.
    if wm.byok_is_active and not wm.byok_current_supports_vision:
        note = layout.row(align=True)
        note.active = False
        note.label(
            text="Text-only model — 3D tasks run without visual feedback.",
            icon='INFO',
        )


def _draw_form(layout, wm, disabled: bool):
    box = layout.box()
    col = box.column(align=True)
    col.enabled = not disabled
    _draw_field(col, wm, 'byok_form_provider', "Provider")

    provider = wm.byok_form_provider
    if model_suggestions.is_openrouter(provider):
        _draw_openrouter_fields(box, col, wm)
    elif model_suggestions.is_codex(provider):
        _draw_codex_fields(box, col, wm)
    else:
        _draw_cloud_fields(box, col, wm)


def _draw_cloud_fields(box, col, wm):
    _draw_field(col, wm, 'byok_form_model', "Model")
    _draw_field(col, wm, 'byok_form_api_key', "API Key")
    _draw_hint(box, "Stored encrypted, used only for Mixar agent requests.")


def _draw_openrouter_fields(box, col, wm):
    """Free-text model slug + API key for OpenRouter (base_url is fixed)."""
    _draw_field(col, wm, 'byok_form_openrouter_model', "Model")
    _draw_field(col, wm, 'byok_form_api_key', "API Key")

    warn = box.row()
    warn.alert = True
    warn.label(
        text="Pick a model that supports tool calling — the agent needs it.",
        icon='ERROR',
    )
    _draw_hint(box, "Any slug from openrouter.ai/models, stored encrypted.")


def _draw_codex_fields(box, col, wm):
    """Model slug + auto-load / paste of the ~/.codex/auth.json token bundle."""
    _draw_field(col, wm, 'byok_form_codex_model', "Model")

    label = col.row()
    label.active = False
    label.label(text="Credentials")

    # One row: load straight off this machine, or paste from the clipboard.
    # The field itself sits between them because a manual paste into a
    # single-line prop can't carry the multi-line JSON.
    creds = col.row(align=True)
    creds.scale_y = 1.45
    creds.operator(
        "mixar_byok.codex_load_file", text="Load auth.json", icon='FILE_REFRESH',
    )
    creds.prop(wm, 'byok_form_codex_bundle', text="")
    creds.operator("mixar_byok.codex_paste", text="", icon='PASTEDOWN')

    text, icon = codex_bundle_status(wm.byok_form_codex_bundle)
    status = col.row()
    status.active = False
    status.label(text=text, icon=icon)
    col.separator(factor=0.45)

    _draw_hint(box, "Run  codex login  first — uses your ChatGPT subscription.")


def _draw_field(layout, data, prop_name: str, label: str):
    """A labelled full-width field, stacked label-over-input."""
    label_row = layout.row()
    label_row.active = False
    label_row.label(text=label)

    field_row = layout.row()
    field_row.scale_y = 1.45
    field_row.prop(data, prop_name, text="")
    layout.separator(factor=0.45)


def _draw_hint(box, text: str):
    row = box.row()
    row.active = False
    row.label(text=text, icon='INFO')


def _draw_error(layout, wm):
    layout.separator(factor=0.4)
    err_box = layout.box()
    err_box.alert = True
    err_col = err_box.column(align=True)
    err_col.label(text="Save failed", icon='ERROR')
    for line in wrap(wm.byok_last_error, width=ERROR_WRAP_WIDTH):
        err_col.label(text=line)


def _draw_actions(layout, wm, saving: bool):
    """Footer: the blocker hint on the left, Remove / Save on the right.

    Save keeps its slot and label geometry while saving — only the text
    and enabled state change — so the footer never changes height.
    """
    row = layout.row(align=True)
    row.scale_y = 1.35

    blocker = save_blocker(wm)
    hint = row.row(align=True)
    hint.active = False
    if saving:
        hint.label(text="Validating with provider...", icon='SORTTIME')
    elif blocker:
        hint.label(text=blocker)
    else:
        hint.label(text="")

    buttons = row.row(align=True)
    buttons.alignment = 'RIGHT'
    buttons.enabled = not saving
    if wm.byok_is_active:
        remove = buttons.row(align=True)
        remove.alert = True
        remove.operator("mixar_byok.request_remove", text="Remove", icon='TRASH')
    buttons.operator(
        "mixar_byok.save",
        text="Saving..." if saving else "Save",
        icon='SORTTIME' if saving else 'CHECKMARK',
    )


def _draw_remove_confirm(layout):
    """Inline confirmation, in the footer's place.

    Deliberately not a full-body takeover: the status and form stay put
    above, so the user can still see what they're about to remove.
    """
    warn = layout.column(align=True)
    warn.active = False
    warn.label(
        text="Removing returns the agent to Mixar's provider — credits will be charged.",
        icon='QUESTION',
    )

    row = layout.row(align=True)
    row.scale_y = 1.35
    row.operator("mixar_byok.cancel_remove", text="Cancel", icon='CANCEL')
    confirm = row.row(align=True)
    confirm.alert = True
    confirm.operator("mixar_byok.confirm_remove", text="Remove Key", icon='TRASH')
