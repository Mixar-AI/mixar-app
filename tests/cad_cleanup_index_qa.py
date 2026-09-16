# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/scripts'))
import bpy
from mixar.modules.common.cad_cleanup.core import state, mutations

scene = bpy.context.scene
roots = []
for i in range(15):
    coll = bpy.data.collections.new('Index QA ' + str(i))
    scene.collection.children.link(coll)
    roots.append(coll)
for i in range(500):
    ob = bpy.data.objects.new('Object ' + str(i), None)
    roots[i % 15].objects.link(ob)
    if i % 7 == 0: roots[(i + 1) % 15].objects.link(ob)
    ob.hide_render = i % 11 == 0
roots[2].hide_render = True
bpy.context.view_layer.layer_collection.children[roots[3].name].exclude = True
bpy.context.view_layer.update()
indexes = state.relations()
eligible = state.render_eligible_ids()
for obj in scene.objects:
    assert (obj.as_pointer() in eligible) == mutations._render_eligible(obj), obj.name
    assert sorted(indexes[0][obj.as_pointer()]) == sorted(c.name for c in obj.users_collection)
    assert (obj.as_pointer() in indexes[1]) == bool(obj.children)
start = time.perf_counter()
run = state.start({'owner_id':'perf-qa', 'request_id':'start'})
assert len(run['records']) == len(scene.objects)
assert state.digest(state.capture(run)) == run['fingerprint']
print('CAD_INDEX_QA_PASS', len(scene.objects), 'start_seconds', time.perf_counter()-start)
from mixar.modules.common.cad_cleanup.api import dispatch
owner = {'owner_id':'perf-qa', 'run_id':run['run_id']}
preview = dispatch('analyze', {**owner, 'stage':'1'})
assert preview['success'], preview
scene.objects[0].location.x += 1
page = dispatch('inspect', {**owner, 'proposal_id':preview['proposal_id']})
assert page['success'] and page['live_geometry_checked'] is False, page
applied = dispatch('apply', {**owner, 'proposal_id':preview['proposal_id'], 'request_id':'stale'})
assert not applied['success'] and applied['error']['code']=='scene_changed', applied
print('CAD_STORED_PREVIEW_STALE_APPLY_REJECTED')
