# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Guest profile routes and browser-state rendering, without Blender."""

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from mixar.modules.common.utils import topbar_layout
from mixar.modules.space_mixie_chat.ui import login_panel

TOPBAR = Path(__file__).resolve().parents[1] / "src/scripts/mixar/modules/space_mixie_chat/ui/topbar.py"
NAMESPACE = {"topbar_layout": topbar_layout, "bpy": MagicMock()}


def wm(**overrides):
    values = dict(mixie_chat_is_logged_in=True, mixie_chat_is_guest=True,
                  mixie_chat_is_logging_in=False, mixie_chat_session_expired=False,
                  mixie_chat_login_error="", byok_is_active=False)
    return SimpleNamespace(**(values | overrides))


@pytest.mark.parametrize("logged_in,guest,expected", [
    (False, False, False), (False, True, False),
    (True, True, False), (True, False, True),
])
def test_guest_session_is_never_a_personal_account(logged_in, guest, expected):
    assert topbar_layout.account_signed_in(wm(
        mixie_chat_is_logged_in=logged_in, mixie_chat_is_guest=guest)) is expected


@pytest.mark.parametrize("pending", [False, True])
def test_card_and_legacy_panel_share_pending_and_cancel_behavior(pending):
    for card in (False, True):
        layout = MagicMock()
        login_panel.draw_browser_sign_in(layout, wm(mixie_chat_is_logging_in=pending), card=card)
        ops = [call.args[0] for call in layout.operator.call_args_list]
        assert ops == ["mixie_chat.cancel_login" if pending else "mixie_chat.login"]
        if pending:
            layout.label.assert_called_once_with(text="Continue in your browser", icon='SORTTIME')
        if card:
            layout.mixar_card_button.assert_called_once_with(kind='GHOST' if pending else 'ACCENT')


def test_profile_draws_sign_in_before_tools():
    # bpy.types.Panel is mocked; execute its draw method as an ordinary function.
    tree = ast.parse(TOPBAR.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MIXAR_PT_profile')
    draw = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'draw')
    ns = dict(NAMESPACE)
    layout = MagicMock()
    ns['draw_profile_sign_in'] = lambda layout, state: layout.record_sign_in()
    exec(compile(ast.Module(body=[draw], type_ignores=[]), '<profile draw>', 'exec'), ns)
    ns['draw'](SimpleNamespace(layout=layout), SimpleNamespace(window_manager=wm()))
    assert [call[0] for call in layout.mock_calls] == ['record_sign_in', 'mixar_profile_card']
    layout.reset_mock()
    ns['draw'](SimpleNamespace(layout=layout), SimpleNamespace(window_manager=wm(mixie_chat_is_guest=False)))
    assert [call[0] for call in layout.mock_calls] == ['mixar_profile_card']


@pytest.mark.parametrize("guest", [False, True])
def test_fallback_does_not_expose_account_actions_to_guest(guest):
    tree = ast.parse(TOPBAR.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MIXAR_PT_profile')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_draw_fallback_menu')
    method.decorator_list = []
    ns = dict(NAMESPACE)
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<fallback>', 'exec'), ns)
    layout = MagicMock()
    ns['_draw_fallback_menu'](SimpleNamespace(window_manager=wm(mixie_chat_is_guest=guest)), layout)
    ops = [c.args[0] for c in layout.mock_calls if c[0].endswith('operator')]
    assert ('mixie_chat.logout' in ops) is not guest
    assert ('mixie_chat.open_dashboard' in ops) is not guest
    assert 'mixar_byok.open_dialog' in ops and 'mixar.connect_ai' in ops


@pytest.mark.parametrize("width", [448, 560, 900, 1512, 2000])
@pytest.mark.parametrize("engine", [False, True])
def test_translated_guest_caption_has_same_budget_as_account(width, engine):
    label = 'Gastbenutzer'
    sound = topbar_layout.show_sound_toggle(width, engine=engine, logged_in=False)
    units, rendered = topbar_layout.profile_pill(label, width, engine=engine, sound=sound)
    budget = topbar_layout._account_budget_units(width, engine, sound)
    assert units <= max(budget, topbar_layout.PROFILE_AVATAR_UNITS)
    assert topbar_layout.full_account_units(False, 'stale@example.invalid', label) == (
        len(label) * topbar_layout.PROFILE_CHAR_UNITS + topbar_layout.PROFILE_BASE_UNITS)
