# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/scripts'))
import bpy
from mixar.modules.common.cad_cleanup.core import state, visual

run = state.start({'owner_id':'cache-qa', 'request_id':'start'})
first = visual.render(run, {'view':'front'})
assert first['cached'] is False
assert not any(s.name.startswith('CAD Inspection Temporary') for s in bpy.data.scenes)
# Simulate the original response being lost and local state read on retry.
run = state.read({'owner_id':'cache-qa', 'run_id':run['run_id']})
again = visual.render(run, {'view':'front'})
assert again['cached'] is True and again['evidence_id'] == first['evidence_id']
assert again['image_base64'] == first['image_base64']
other = visual.render(run, {'view':'rear'})
assert other['cached'] is False and other['evidence_id'] != first['evidence_id']
key = next(k for k,o in state.objects(run).items() if o.type == 'MESH')
subset = visual.render(run, {'view':'front', 'object_ids':[key]})
assert subset['cached'] is False
state.refresh(run)
run['revision'] += 1
revised = visual.render(run, {'view':'front'})
assert revised['cached'] is False
path = visual.cached_path(run['evidence'][revised['evidence_id']])
path.unlink()
missing = visual.render(run, {'view':'front'})
assert missing['cached'] is False
assert visual.cached_path({'image_file':'../../source.mixar'}) is None
print('CAD_RENDER_RECOVERY_PASS: exact retry, persisted state, view, subset, revision, missing image, path confinement')
