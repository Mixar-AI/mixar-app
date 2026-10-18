# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Account identity is session-wide, regardless of stored Scene values."""

from types import SimpleNamespace

import pytest

from mixar.modules.space_mixie_chat.core import account_identity as identity


@pytest.fixture(autouse=True)
def reset_identity(monkeypatch):
    monkeypatch.setattr(identity, '_email', '')
    monkeypatch.setattr(identity, '_values', {})
    monkeypatch.setattr(identity, '_session_props', set())


def test_file_identity_is_never_adopted():
    assert identity.get_email(None, 'author@example.invalid', True) == ''
    assert identity.set_email(None, 'reader@example.invalid', '', False) == ''
    assert identity.get_email(None, 'author@example.invalid', True) == 'reader@example.invalid'


def test_all_scenes_share_login_and_logout():
    first, second = object(), object()
    identity.set_email(first, 'reader@example.invalid', '', False)
    assert identity.get_email(second, '', False) == 'reader@example.invalid'
    identity.set_email(second, '', '', True)
    assert identity.get_email(first, 'author@example.invalid', True) == ''


def test_migration_removes_both_storage_kinds_without_changing_account(monkeypatch):
    class Scene(dict):
        def property_unset(self, name):
            self.unset = name

    scenes = [Scene(mixie_chat_user_id='author@example.invalid'), Scene()]
    monkeypatch.setattr(identity, 'bpy', SimpleNamespace(
        data=SimpleNamespace(scenes=scenes, window_managers=[])))
    identity.set_email(None, 'reader@example.invalid', '', False)
    identity.remove_saved_identity()
    assert all(scene.unset == 'mixie_chat_user_id' for scene in scenes)
    assert all('mixie_chat_user_id' not in scene for scene in scenes)
    assert identity.get_email(None, '', False) == 'reader@example.invalid'


def test_file_sign_in_flags_are_never_adopted():
    """Opening a file saved by a signed-in account keeps the live guest."""
    logged_in = identity.session_value('mixie_chat_is_logged_in')
    is_guest = identity.session_value('mixie_chat_is_guest')
    assert logged_in['set_transform'](None, True, False, False) is False
    assert is_guest['set_transform'](None, True, False, False) is False
    # The adopted WindowManager stored "account, not guest".
    assert logged_in['get_transform'](None, True, True) is True
    assert is_guest['get_transform'](None, False, True) is True
    is_guest['set_transform'](None, False, True, True)
    assert is_guest['get_transform'](None, True, True) is False


def test_migration_removes_saved_session_values(monkeypatch):
    names = ('mixie_chat_is_guest', 'mixar_usage_credits_remaining')

    class WindowManager(dict):
        bl_rna = SimpleNamespace(properties=dict.fromkeys(names))

        def property_unset(self, name):
            self.unset = getattr(self, 'unset', set()) | {name}

    wm = WindowManager(mixie_chat_is_guest=0, mixar_usage_credits_remaining=900)
    monkeypatch.setattr(identity, 'bpy', SimpleNamespace(
        data=SimpleNamespace(scenes=[], window_managers=[wm])))
    guest = identity.session_value('mixie_chat_is_guest')
    credits = identity.session_value('mixar_usage_credits_remaining', 0)
    guest['set_transform'](None, True, False, False)
    credits['set_transform'](None, 40, 0, False)
    identity.remove_saved_identity()
    assert wm.unset == set(names)
    assert not wm
    assert guest['get_transform'](None, False, False) is True
    assert credits['get_transform'](None, 900, True) == 40


def test_file_account_name_is_never_adopted():
    name = identity.session_value('mixar_account_name', '')
    assert name['set_transform'](None, 'Reader', '', False) == ''
    assert name['get_transform'](None, 'Author', True) == 'Reader'
