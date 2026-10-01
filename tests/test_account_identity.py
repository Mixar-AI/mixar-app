# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Account identity is session-wide, regardless of stored Scene values."""

from types import SimpleNamespace

import pytest

from mixar.modules.space_mixie_chat.core import account_identity as identity


@pytest.fixture(autouse=True)
def reset_identity(monkeypatch):
    monkeypatch.setattr(identity, '_email', '')


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
    monkeypatch.setattr(identity, 'bpy', SimpleNamespace(data=SimpleNamespace(scenes=scenes)))
    identity.set_email(None, 'reader@example.invalid', '', False)
    identity.remove_saved_identity()
    assert all(scene.unset == 'mixie_chat_user_id' for scene in scenes)
    assert all('mixie_chat_user_id' not in scene for scene in scenes)
    assert identity.get_email(None, '', False) == 'reader@example.invalid'
