# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Actual registration with RNA readiness and late-allocation failure injection."""
import importlib.util
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def keymap(monkeypatch):
    path = Path(__file__).parents[1] / 'src/scripts/mixar/modules/space_mixie_chat/ui/keymap.py'
    spec = importlib.util.spec_from_file_location('qa_chat_keymap', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    live = []
    state = {'ready': False}

    class Properties:
        def __setattr__(self, key, value):
            if not state['ready']:
                raise AttributeError('origin RNA not registered yet')
            object.__setattr__(self, key, value)

    def new(idname, **kw):
        item = SimpleNamespace(idname=idname, properties=Properties())
        live.append(item)
        return item

    km = SimpleNamespace(keymap_items=SimpleNamespace(new=new, remove=live.remove))
    kc = SimpleNamespace(keymaps=SimpleNamespace(new=lambda **kw: km))
    timers = Mock()
    timers.is_registered.return_value = False
    monkeypatch.setattr(module, 'bpy', SimpleNamespace(
        context=SimpleNamespace(window_manager=SimpleNamespace(keyconfigs=SimpleNamespace(addon=kc))),
        app=SimpleNamespace(timers=timers)))
    monkeypatch.setattr(module, '_register_voice_push_to_talk', lambda kc: None)
    return module, live, state, km


def test_rna_failure_rolls_back_and_retry_is_complete_and_idempotent(keymap):
    module, live, state, _ = keymap
    with pytest.raises(AttributeError, match='origin'):
        module.register()
    assert not live and not module.addon_keymaps
    state['ready'] = True
    module.register()
    assert {'mixie_chat.copy', 'mixie_chat.select_text', 'mixie_chat.abort_session'} <= {i.idname for i in live}
    assert next(i for i in live if i.idname == 'mixie_chat.abort_session').properties.origin == 'escape_key'
    count = len(live)
    module.register()
    assert len(live) == count
    module.unregister()
    assert not live and not module.addon_keymaps


def test_failure_after_last_chat_item_still_rolls_back_all_items(keymap, monkeypatch):
    module, live, state, km = keymap
    state['ready'] = True

    def fail_voice(kc):
        item = km.keymap_items.new('mixie_chat.voice_push_to_talk_release')
        module.addon_keymaps.append((km, item))
        raise RuntimeError('late keymap failure')

    monkeypatch.setattr(module, '_register_voice_push_to_talk', fail_voice)
    with pytest.raises(RuntimeError, match='late keymap'):
        module.register()
    assert not live and not module.addon_keymaps


def test_unregister_cancels_deferred_registration(keymap):
    module, _, _, _ = keymap
    module.bpy.app.timers.is_registered.return_value = True
    module.unregister()
    module.bpy.app.timers.unregister.assert_called_once_with(module.register)


def _startup_bootstrap():
    path = Path(__file__).parents[1] / 'src/scripts/startup/bootstrap/__init__.py'
    spec = importlib.util.spec_from_file_location('qa_startup_bootstrap', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_keymaps_register_after_every_operator_and_before_panels():
    # Regression: ui/keymap.py is shallower than ui/operators/session_ops.py, so it
    # sorted first and ``kmi.properties.origin`` raised (abort_session unregistered);
    # the chat keymap waited for the retry pass at the end of deferred loading.
    bootstrap = _startup_bootstrap()
    modules = Path(__file__).parents[1] / 'src/scripts/mixar/modules'
    order = [p.relative_to(modules).as_posix() for p in bootstrap._discover_ui_files(modules)]
    keymaps = [i for i, p in enumerate(order) if 'keymap' in p.rsplit('/', 1)[-1]]
    # Operator files named like display code (``layer_menus.py``) load with panels.
    operators = [i for i, p in enumerate(order) if '/ui/operators/' in p
                 and not any(kw in p.rsplit('/', 1)[-1] for kw in bootstrap._DISPLAY_KEYWORDS)]
    assert order.index('space_mixie_chat/ui/operators/session_ops.py') in operators
    panels = [i for i, p in enumerate(order) if '/ui/panels/' in p]
    assert 'space_mixie_chat/ui/keymap.py' in order
    assert keymaps and operators and panels
    assert max(operators) < min(keymaps) and max(keymaps) < min(panels)


def test_profile_card_loads_after_every_operator_it_draws():
    # Regression: space_mixie_chat/ui/topbar.py sorted as an operator file, ~380
    # modules ahead of billing_ops.py, so the profile card drew
    # MIXAR_OT_open_billing before it registered (native crash on Windows).
    root = Path(__file__).parents[1]
    bootstrap = _startup_bootstrap()
    modules = root / 'src/scripts/mixar/modules'
    order = [p.relative_to(modules).as_posix() for p in bootstrap._discover_ui_files(modules)]
    topbar = order.index('space_mixie_chat/ui/topbar.py')
    drawn = set()
    for src in ('src/scripts/mixar/modules/space_mixie_chat/ui/topbar.py',
                'src/source/blender/editors/interface/interface_mixar_profile_card.cc'):
        text = (root / src).read_text(encoding='utf-8')
        drawn |= {f'{a.lower()}.{b}' for a, b in re.findall(r'\b([A-Z][A-Z_]*)_OT_([a-z_]+)', text)}
        drawn |= set(re.findall(r'operator\(\s*[\'"]([a-z_]+\.[a-z_]+)[\'"]', text))
    assert 'mixar.open_billing' in drawn
    definers = {}
    for i, rel in enumerate(order):
        text = (modules / rel).read_text(encoding='utf-8')
        for idname in drawn:
            if re.search(rf'bl_idname\s*=\s*[\'"]{re.escape(idname)}[\'"]', text):
                definers[idname] = (i, rel)
    assert 'mixar.open_billing' in definers
    late = {k: rel for k, (i, rel) in definers.items() if i > topbar}
    assert not late, f'topbar.py loads before the operators it draws: {late}'
