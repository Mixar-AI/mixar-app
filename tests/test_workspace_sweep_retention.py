# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""An inactive session must not authorize destruction of uncertain workspace output."""

from types import SimpleNamespace
import sys

import pytest

from mixar.modules.space_mixie_chat.core import lane_scene_sweep as sweep


class ID(dict):
    def __init__(self, name, **props):
        super().__init__(props)
        self.name = name

    def __eq__(self, other):
        return self is other


def scene(name, objects=(), *, token='', parent='main-session'):
    value = ID(name, mixar_workspace_main_session=parent)
    if token:
        value['mixar_workspace_token'] = token
    value.mixie_session_id = 'agentlane:' + name
    value.collection = SimpleNamespace(all_objects=list(objects))
    return value


@pytest.fixture
def data(monkeypatch):
    main = scene('Main')
    main.mixie_session_id = 'main-session'
    removed = []
    data = SimpleNamespace(scenes=[main], collections=[], window_managers=[],
                           objects=SimpleNamespace(remove=lambda obj, **kw: removed.append(obj)))
    monkeypatch.setattr(sys.modules['bpy'], 'data', data)
    monkeypatch.setenv('MIXAR_SCENES_DOSSIER_DIR', '0')
    from mixar.modules.space_mixie_chat.core import session
    monkeypatch.setattr(session, 'get_session_manager', lambda: SimpleNamespace(has_active_session=lambda *a: False))
    data.main, data.removed = main, removed
    return data


def test_inactive_parent_retains_uncommitted_owned_output(data):
    obj = ID('Wall')  # Backend tags ordinary output only when it publishes.
    lane = scene('Owned', [obj], token='token')
    data.scenes.append(lane)
    assert sweep.sweep_leaked_lane_scenes('main-session') == 0
    assert lane in data.scenes and not data.removed


@pytest.mark.parametrize('props', [
    {'mixar_workspace_token': 'token', 'mixar_workspace_source': 'Wall'},
    {'mixar_workspace_token': 'other', 'mixar_workspace_helper': 'camera'},
    {'mixar_workspace_token': 'token', 'mixar_workspace_source': 'Wall', 'mixar_workspace_helper': 'camera'},
])
def test_clone_and_foreign_helper_are_output_not_disposable_helpers(data, props):
    lane = scene('Owned', [ID('Copy', **props)], token='token')
    data.scenes.append(lane)
    assert not sweep._remove_lane_scene(lane)
    assert not data.removed


@pytest.mark.parametrize('state', ['preparing', 'unknown-new-state'])
def test_empty_scene_with_incomplete_merge_transaction_is_retained(data, state):
    lane = scene('Owned', token='token')
    data.scenes.append(lane)
    data.collections.append(ID('Transaction', mixar_workspace_token='token', mixar_workspace_state=state))
    assert not sweep._remove_lane_scene(lane)
    assert lane in data.scenes


def test_transaction_plan_without_state_is_not_treated_as_empty(data):
    lane = scene('Owned', token='token')
    data.scenes.append(lane)
    data.collections.append(ID('Transaction', mixar_workspace_token='token', mixar_workspace_merge_plan='{}'))
    assert not sweep._remove_lane_scene(lane)
    assert lane in data.scenes


@pytest.mark.parametrize('committed', [False, True])
def test_proven_helper_only_scene_can_be_swept(data, committed):
    helper = ID('Camera', mixar_workspace_token='token', mixar_workspace_helper='camera')
    lane = scene('Owned', [helper], token='token')
    data.scenes.append(lane)
    if committed:
        data.collections.append(ID('Transaction', mixar_workspace_token='token', mixar_workspace_state='committed'))
    assert sweep.sweep_leaked_lane_scenes('main-session') == 1
    assert lane not in data.scenes and data.removed == [helper]


def test_unreadable_inventory_fails_closed(data):
    class BrokenCollection:
        @property
        def all_objects(self):
            raise ReferenceError('stale RNA')

    lane = scene('Owned', token='token')
    lane.collection = BrokenCollection()
    data.scenes.append(lane)
    assert not sweep._remove_lane_scene(lane)
    assert lane in data.scenes and not data.removed


def test_legacy_cleanup_preserves_every_object_linked_to_another_scene(data):
    shared, private = ID('Shared'), ID('Private')
    data.main.collection.all_objects.append(shared)
    lane = scene('Legacy', [shared, private])
    data.scenes.append(lane)
    assert sweep.sweep_leaked_lane_scenes('main-session') == 1
    assert data.removed == [private]
    assert data.main.collection.all_objects == [shared]


def test_missing_scene_ownership_metadata_fails_closed(data):
    class BrokenScene(ID):
        def get(self, *args):
            raise ReferenceError('stale RNA')

    lane = BrokenScene('Broken')
    data.scenes.append(lane)
    assert not sweep._remove_lane_scene(lane)
    assert lane in data.scenes and not data.removed
