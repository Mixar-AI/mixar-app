# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""AI Provider Settings dialog — card design + one-action contract.

Two layers of pinning:

- Functional: `draw_dialog` runs against a fake uiLayout, once with the
  Mixar card API present and once without (old-C++ fallback). Every
  dialog state must render crash-free in both modes, and in card mode
  every state must mark exactly ONE button as the active default — the
  flag that suppresses the props dialog's automatic OK/Cancel row (the
  old redundant Save + OK pair) and gives Return a single meaning.

- Source-level: the C++ this rests on can't be compiled by this suite,
  so the RNA functions, the enum sentinel rule, and the native-row
  suppression guard are pinned by scanning the overlay sources — same
  approach as tests/test_usage_meter.py.
"""

import re
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.byok.constants import DIALOG_STATE_ITEMS
from mixar.modules.byok.core import model_suggestions
from mixar.modules.byok.ui.operators import byok_dialog_ui, byok_ops

INTERFACE_DIR = ROOT / "src" / "source" / "blender" / "editors" / "interface"
RNA_UI_API = ROOT / "src" / "source" / "blender" / "makesrna" / "intern" / "rna_ui_api.cc"
WM_OPERATORS = (
    ROOT / "src" / "source" / "blender" / "windowmanager" / "intern" / "wm_operators.cc"
)

ALL_STATES = tuple(item[0] for item in DIALOG_STATE_ITEMS)


# ---------------------------------------------------------------------------
# Fake uiLayout
# ---------------------------------------------------------------------------


class FakeLayout:
    """Minimal uiLayout stand-in. ``card_api=True`` exposes the Mixar
    card/template methods; False models a build whose C++ predates them."""

    def __init__(self, log, card_api):
        self._log = log
        self._card_api = card_api
        self.enabled = True
        self.alert = False
        self.alignment = 'EXPAND'
        self.scale_y = 1.0
        self.use_property_split = False
        self.use_property_decorate = False

    # -- sublayouts --
    def _sub(self):
        return FakeLayout(self._log, self._card_api)

    def row(self, align=False):
        return self._sub()

    def column(self, align=False):
        return self._sub()

    def split(self, factor=0.0, align=False):
        return self._sub()

    def box(self):
        self._log.append("box")
        return self._sub()

    # -- items --
    def label(self, text="", icon='NONE'):
        self._log.append(f"label:{text}")

    def prop(self, data, prop, text="", expand=False):
        self._log.append(f"prop:{prop}")

    def operator(self, op, text="", icon='NONE'):
        self._log.append(f"op:{op}")
        return SimpleNamespace()

    def separator(self, factor=1.0):
        pass

    # -- Mixar card API (conditionally present) --
    def __getattr__(self, name):
        if name in (
            'mixar_card_label',
            'mixar_card_button',
            'mixar_section',
            'mixar_dropdown',
            'mixar_input',
            'template_popup_confirm',
        ):
            if not self.__dict__['_card_api']:
                raise AttributeError(name)
            return getattr(self, f"_impl_{name}")
        raise AttributeError(name)

    def _impl_mixar_card_label(self, text="", kind='MUTED'):
        self._log.append(f"card_label:{kind}:{text}")

    def _impl_mixar_card_button(self, kind='CARD', active_default=False):
        self._log.append(f"card_button:{kind}:{active_default}")

    def _impl_mixar_section(self):
        self._log.append("section")
        return self._sub()

    def _impl_mixar_dropdown(self, data, prop, text=""):
        self._log.append(f"dropdown:{prop}")

    def _impl_mixar_input(self, data, prop, text=""):
        self._log.append(f"input:{prop}")

    def _impl_template_popup_confirm(self, operator, text="", cancel_text=""):
        self._log.append(f"popup_confirm:{cancel_text}")


def _wm(state='IDLE', **extra):
    wm = SimpleNamespace(
        byok_dialog_state=state,
        byok_is_active=False,
        byok_current_provider='',
        byok_current_model='',
        byok_current_supports_vision=True,
        byok_key_preview='',
        byok_form_provider='NONE',
        byok_form_model='NONE',
        byok_form_api_key='',
        byok_form_openrouter_model='',
        byok_form_codex_model='',
        byok_form_codex_bundle='',
        byok_form_local_mode='MANAGED',
        byok_form_local_model='NONE',
        byok_form_local_detected='NONE',
        byok_form_local_custom_base='',
        byok_form_local_custom_model='',
        byok_form_local_custom_key='',
        byok_last_error='some error text',
    )
    for key, value in extra.items():
        setattr(wm, key, value)
    return wm


def _draw(state, card_api, **wm_extra):
    log = []
    layout = FakeLayout(log, card_api)
    byok_dialog_ui.draw_dialog(layout, _wm(state, **wm_extra))
    return log


# ---------------------------------------------------------------------------
# One-action contract
# ---------------------------------------------------------------------------


def test_every_state_marks_exactly_one_active_default_button():
    """The active-default button is what suppresses the native OK/Cancel
    row — zero would resurrect the redundant pair, two would make Return
    ambiguous."""
    for state in ALL_STATES:
        log = _draw(state, card_api=True, byok_is_active=True,
                    byok_current_provider='anthropic', byok_current_model='m')
        defaults = [e for e in log if e.startswith("card_button:") and e.endswith(":True")]
        assert len(defaults) == 1, f"{state}: expected 1 default button, log={log}"


def test_footer_actions_per_state():
    # IDLE with an active config: Cancel + Save, and Remove lives in the
    # config card (not the footer) — three distinct, unambiguous actions.
    log = _draw('IDLE', card_api=True, byok_is_active=True,
                byok_current_provider='anthropic', byok_current_model='m')
    assert "popup_confirm:Cancel" in log
    assert f"op:{byok_dialog_ui.OP_SAVE}" in log
    assert f"op:{byok_dialog_ui.OP_REQUEST_REMOVE}" in log
    assert "card_button:ACCENT:True" in log

    # Fresh setup: no Remove anywhere.
    log = _draw('IDLE', card_api=True)
    assert f"op:{byok_dialog_ui.OP_REQUEST_REMOVE}" not in log

    # Error retries through the same save operator.
    log = _draw('ERROR', card_api=True)
    assert f"op:{byok_dialog_ui.OP_SAVE}" in log

    # Confirm-remove offers exactly keep/remove, keep is the default.
    log = _draw('CONFIRM_REMOVE', card_api=True, byok_is_active=True)
    assert f"op:{byok_dialog_ui.OP_CANCEL_REMOVE}" in log
    assert f"op:{byok_dialog_ui.OP_CONFIRM_REMOVE}" in log
    assert "card_button:CARD:True" in log      # Keep My Key
    assert "card_button:DANGER:False" in log   # Remove API Key

    # The recap states close through a single Done button.
    for state in ('SAVED', 'REMOVED'):
        log = _draw(state, card_api=True, byok_is_active=(state == 'SAVED'))
        assert "popup_confirm:Done" in log
        assert f"op:{byok_dialog_ui.OP_SAVE}" not in log

    # Busy states keep the primary slot as a progress pill; no Cancel/Save pair.
    for state in ('SAVING', 'REMOVING'):
        log = _draw(state, card_api=True, byok_is_active=True)
        assert not any(e.startswith("popup_confirm:") for e in log)


def test_dialog_never_draws_its_own_ok_button():
    source = (SCRIPTS / "mixar" / "modules" / "byok" / "ui" / "operators"
              / "byok_dialog_ui.py").read_text()
    assert '"OK"' not in source and "'OK'" not in source


def test_all_states_render_without_card_api():
    """Old-C++ fallback: stock widgets only, still crash-free."""
    for state in ALL_STATES:
        for active in (False, True):
            _draw(state, card_api=False, byok_is_active=active,
                  byok_current_provider='anthropic', byok_current_model='m')


def test_all_provider_branches_render_in_both_modes():
    for provider, extra in (
        ('anthropic', {}),
        ('openrouter', {'byok_form_openrouter_model': 'a/b'}),
        ('codex', {'byok_form_codex_bundle': 'x' * 10}),
        ('local', {'byok_form_local_mode': 'MANAGED'}),
        ('local', {'byok_form_local_mode': 'CUSTOM'}),
    ):
        for card_api in (True, False):
            _draw('IDLE', card_api, byok_form_provider=provider, **extra)


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


def test_dialog_states_cover_the_full_flow():
    assert ALL_STATES == (
        'IDLE', 'SAVING', 'REMOVING', 'SAVED', 'REMOVED', 'ERROR', 'CONFIRM_REMOVE',
    )


def test_save_success_lands_on_saved_recap(monkeypatch):
    wm = _wm('IDLE', byok_form_provider='openai', byok_form_model='gpt-5',
             byok_form_api_key='sk-secret')
    context = SimpleNamespace(window_manager=wm)
    monkeypatch.setattr(byok_ops, "_redraw_mixie_chat_areas", lambda: None)
    monkeypatch.setattr(byok_ops.bpy.context, "window_manager", wm, raising=False)
    monkeypatch.setattr(
        byok_ops.byok_client, "save_credentials",
        lambda **kwargs: kwargs["on_done"](True, {
            "byok_active": True,
            "items": [{"provider": "openai", "model": "gpt-5",
                       "key_preview": "sk-…ret", "supports_vision": True}],
        }, None),
    )
    model_suggestions.populate(
        providers=[("openai", "OpenAI", "OpenAI")],
        models={"openai": [("gpt-5", "GPT-5", "GPT-5")]},
    )
    try:
        assert byok_ops.MIXAR_BYOK_OT_save().execute(context) == {'FINISHED'}
    finally:
        model_suggestions.clear()

    assert wm.byok_dialog_state == 'SAVED'
    assert wm.byok_is_active is True
    assert wm.byok_form_api_key == ''  # secret wiped after landing


def test_save_failure_lands_on_error(monkeypatch):
    wm = _wm('IDLE', byok_form_provider='openai', byok_form_model='gpt-5',
             byok_form_api_key='sk-secret')
    context = SimpleNamespace(window_manager=wm)
    monkeypatch.setattr(byok_ops, "_redraw_mixie_chat_areas", lambda: None)
    monkeypatch.setattr(byok_ops.bpy.context, "window_manager", wm, raising=False)
    monkeypatch.setattr(
        byok_ops.byok_client, "save_credentials",
        lambda **kwargs: kwargs["on_done"](False, None, "key rejected"),
    )
    model_suggestions.populate(
        providers=[("openai", "OpenAI", "OpenAI")],
        models={"openai": [("gpt-5", "GPT-5", "GPT-5")]},
    )
    try:
        byok_ops.MIXAR_BYOK_OT_save().execute(context)
    finally:
        model_suggestions.clear()

    assert wm.byok_dialog_state == 'ERROR'
    assert wm.byok_last_error == "key rejected"


def test_remove_flow_walks_confirm_removing_removed(monkeypatch):
    wm = _wm('IDLE', byok_is_active=True, byok_current_provider='openai')
    context = SimpleNamespace(window_manager=wm)
    monkeypatch.setattr(byok_ops, "_redraw_mixie_chat_areas", lambda: None)
    monkeypatch.setattr(byok_ops.bpy.context, "window_manager", wm, raising=False)

    byok_ops.MIXAR_BYOK_OT_request_remove().execute(context)
    assert wm.byok_dialog_state == 'CONFIRM_REMOVE'

    byok_ops.MIXAR_BYOK_OT_cancel_remove().execute(context)
    assert wm.byok_dialog_state == 'IDLE'

    seen = {}

    def fake_delete(on_done):
        # In-flight state is visible before the callback lands.
        seen['state_during'] = wm.byok_dialog_state
        on_done(True, 1, None)

    monkeypatch.setattr(byok_ops.byok_client, "delete_credentials", fake_delete)
    byok_ops.MIXAR_BYOK_OT_request_remove().execute(context)
    byok_ops.MIXAR_BYOK_OT_confirm_remove().execute(context)

    assert seen['state_during'] == 'REMOVING'
    assert wm.byok_dialog_state == 'REMOVED'
    assert wm.byok_is_active is False
    assert wm.byok_current_provider == ''


def test_remove_failure_lands_on_error(monkeypatch):
    wm = _wm('CONFIRM_REMOVE', byok_is_active=True)
    context = SimpleNamespace(window_manager=wm)
    monkeypatch.setattr(byok_ops, "_redraw_mixie_chat_areas", lambda: None)
    monkeypatch.setattr(byok_ops.bpy.context, "window_manager", wm, raising=False)
    monkeypatch.setattr(
        byok_ops.byok_client, "delete_credentials",
        lambda on_done: on_done(False, 0, "server said no"),
    )
    byok_ops.MIXAR_BYOK_OT_confirm_remove().execute(context)
    assert wm.byok_dialog_state == 'ERROR'
    assert wm.byok_last_error == "server said no"
    assert wm.byok_is_active is True  # config untouched on failure


# ---------------------------------------------------------------------------
# C++ contract pinning (this suite cannot compile the overlay)
# ---------------------------------------------------------------------------


def test_rna_defines_the_card_reuse_functions():
    source = RNA_UI_API.read_text()
    assert '"mixar_card_label", "rna_uiLayoutMixarCardLabel"' in source
    assert '"mixar_card_button", "rna_uiLayoutMixarCardButton"' in source
    # active_default is the OK/Cancel-suppression channel.
    assert '"active_default"' in source


def test_rna_kind_items_cover_every_kind_python_uses():
    rna = RNA_UI_API.read_text()
    label_items = re.search(
        r"mixar_card_label_kind_items\[\]\s*=\s*\{(.*?)\};", rna, re.S).group(1)
    button_items = re.search(
        r"mixar_card_button_kind_items\[\]\s*=\s*\{(.*?)\};", rna, re.S).group(1)

    byok_dir = SCRIPTS / "mixar" / "modules" / "byok"
    python = "\n".join(
        p.read_text() for p in byok_dir.rglob("*.py")
    )
    # No trailing \): multi-line calls end with a comma before the paren.
    label_kinds = set(re.findall(r"card_label\([^)]*?'([A-Z_]+)'", python))
    button_kinds = set(
        re.findall(r"(?:op_button|style_last_button|dismiss_button)\("
                   r"[^)]*?'([A-Z_]+)'", python))
    assert label_kinds, "no card_label kinds found — regex went stale"
    assert button_kinds, "no button kinds found — regex went stale"
    for kind in label_kinds:
        assert f'"{kind}"' in label_items, f"label kind {kind} missing from RNA items"
    for kind in button_kinds:
        assert f'"{kind}"' in button_items, f"button kind {kind} missing from RNA items"


def test_rna_switches_map_every_declared_item():
    """Each RNA enum value must have a case in its runtime switch —
    a missing case silently draws the element as plain/CARD."""
    source = RNA_UI_API.read_text()
    for items_name, fn_name in (
        ("mixar_card_label_kind_items", "rna_uiLayoutMixarCardLabel"),
        ("mixar_card_button_kind_items", "rna_uiLayoutMixarCardButton"),
    ):
        items = re.search(items_name + r"\[\]\s*=\s*\{(.*?)\};", source, re.S).group(1)
        values = re.findall(r"\{(\d+),\s*\"", items)
        fn = re.search(r"static void " + fn_name + r"\(.*?\n\}", source, re.S).group(0)
        for value in values:
            assert f"case {value}:" in fn, f"{fn_name} misses case {value}"


def test_card_element_enum_keeps_count_last():
    header = (INTERFACE_DIR / "interface_mixar_profile_card.hh").read_text()
    enum = re.search(r"enum class MixarCardElement : int \{(.*?)\};", header, re.S).group(1)
    enumerators = re.findall(r"^\s*([A-Za-z_]+),", enum, re.M)
    assert enumerators[-1] == "Count", "Count must stay the last enumerator"
    assert "DangerText" in enumerators
    assert enumerators.index("DangerText") < enumerators.index("Count")


def test_card_taggers_exported_and_danger_text_drawn():
    section = (INTERFACE_DIR / "interface_mixar_section.cc").read_text()
    assert "void UI_layout_mixar_card_tag_last(" in section
    assert "void UI_layout_mixar_card_style_last_button(" in section
    assert "button_flag_enable(but, BUT_ACTIVE_DEFAULT)" in section
    assert "button_flag_disable(but, BUT_ACTIVE_DEFAULT)" in section

    draw = (INTERFACE_DIR / "interface_mixar_profile_card_draw.cc").read_text()
    assert "case MixarCardElement::DangerText:" in draw


def test_native_ok_row_suppression_guard_still_in_place():
    """The whole one-action UX rests on wm_block_dialog_create skipping
    its OK/Cancel pair when the dialog already has a default button. If
    an upstream merge drops that guard, the redundant buttons come back."""
    source = WM_OPERATORS.read_text()
    guard = source.find("block_has_active_default_button")
    assert guard != -1
    # The guard must sit inside wm_block_dialog_create, before the
    # confirm/cancel buttons are defined.
    create = source.find("static ui::Block *wm_block_dialog_create")
    confirm = source.find("button_func_set(confirm_but", create)
    assert create != -1 and confirm != -1
    assert create < guard < confirm
