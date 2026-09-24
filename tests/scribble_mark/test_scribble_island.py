# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Sketch minimizes once; leaving an unsent sketch reveals its preview."""
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from mixar.modules.scribble_mark.core import island, marks, scribble_mode
from mixar.modules.space_mixie_chat.core import scribble


@pytest.mark.parametrize('success', [True, False])
def test_only_a_successful_freeze_minimizes_the_island(monkeypatch, success):
    monkeypatch.setattr(scribble_mode.bpy.ops.mixar, 'scribble_mark_draw',
                        Mock(return_value={'RUNNING_MODAL' if success else 'CANCELLED'}))
    monkeypatch.setattr(scribble_mode, '_warn_marking_unavailable', Mock())
    minimize = Mock()
    monkeypatch.setattr(island, 'minimize', minimize)
    assert scribble_mode.arm(NS()) is success
    assert minimize.call_count == int(success)


def test_minimizing_commits_the_existing_composer_edit_first(monkeypatch):
    release = Mock()
    monkeypatch.setattr(scribble, 'release_composer', release)
    minimize = Mock(side_effect=lambda: release.assert_called_once())
    monkeypatch.setattr(island.bpy.ops.mixar, 'bubble_minimise', minimize)
    island.minimize()
    minimize.assert_called_once()


@pytest.mark.parametrize('text,drafts,expected', [('', 0, False), ('typed', 0, True),
                                                ('', 1, True), ('typed', 1, True)])
def test_reveal_unsent_text_or_sketch_but_not_a_completed_send(monkeypatch, text, drafts, expected):
    monkeypatch.setattr(marks, 'count', lambda *a, **kw: drafts)
    restore = Mock()
    monkeypatch.setattr(island.bpy.ops.mixar, 'bubble_restore', restore)
    island.reveal_draft(NS(scene=NS(mixie_chat_input=text)))
    assert restore.call_count == int(expected)
