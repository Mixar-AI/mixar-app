# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""GUI QA fixture: run(sweep_module) with the branch's lane_scene_sweep module.

Uses a unique inactive parent ID. Leaves retained fixture workspaces in the
file for inspection; never touches a user session or existing object.
"""

from uuid import uuid4

import bpy


def run(sweep):
    stamp = uuid4().hex
    parent = 'qa-retention-' + stamp
    main = bpy.data.scenes.new('QA_Retention_Main_' + stamp[:8])
    main.mixie_session_id = parent

    def lane(label, token=''):
        scene = bpy.data.scenes.new('QA_Retention_' + label + '_' + stamp[:8])
        scene.mixie_session_id = 'agentlane:' + stamp + label
        scene['mixar_workspace_main_session'] = parent
        if token:
            scene['mixar_workspace_token'] = token
        return scene

    owned = lane('Output', stamp)
    output = bpy.data.objects.new('QA_Retained_Wall', None)
    owned.collection.objects.link(output)
    preparing = lane('Preparing', stamp + 'transaction')
    transaction = bpy.data.collections.new('QA_Retention_Transaction_' + stamp[:8])
    transaction['mixar_workspace_token'] = stamp + 'transaction'
    transaction['mixar_workspace_state'] = 'preparing'
    empty = lane('HelperOnly', stamp + 'empty')
    helper = bpy.data.objects.new('QA_Disposable_Helper', None)
    helper['mixar_workspace_token'] = stamp + 'empty'
    helper['mixar_workspace_helper'] = 'camera'
    empty.collection.objects.link(helper)
    legacy = lane('Legacy')
    shared = bpy.data.objects.new('QA_Shared_Output', None)
    main.collection.objects.link(shared)
    legacy.collection.objects.link(shared)
    names = {key: value.name for key, value in
             [('owned', owned), ('preparing', preparing), ('empty', empty), ('legacy', legacy)]}
    helper_name, shared_name = helper.name, shared.name
    removed = sweep.sweep_leaked_lane_scenes(parent_session_id=parent)
    assert removed == 2, removed
    assert names['owned'] in bpy.data.scenes and output.name in owned.objects
    assert names['preparing'] in bpy.data.scenes
    assert names['empty'] not in bpy.data.scenes and helper_name not in bpy.data.objects
    assert names['legacy'] not in bpy.data.scenes and shared_name in main.objects
    return {'success': True, 'removed': removed, 'owned_output_retained': True,
            'preparing_transaction_retained': True, 'shared_object_preserved': True,
            'retained_scenes': [names['owned'], names['preparing']]}
