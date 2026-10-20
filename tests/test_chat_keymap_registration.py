# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Actual registration with RNA readiness and late-allocation failure injection."""
import importlib.util
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
