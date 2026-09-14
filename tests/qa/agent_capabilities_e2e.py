#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Real sandbox helper reuse, compact inspection and GPU preview; no paid calls.

Use the same isolated authoring QA environment as async_preview_e2e.py.
"""
import asyncio
import base64
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
sys.path.insert(0, os.environ['MIXAR_BACKEND'])
from lib import run_scenario
from async_preview_e2e import SETUP, require, script
import fakeredis.aioredis
from modules.agent_next.state import Store
from modules.agent_next.tools import ToolBox
from modules.agent_next.validation import ValidationError

DEVICE_SETTINGS = """p=bpy.context.preferences.addons['cycles'].preferences
result={'device':bpy.context.scene.cycles.device,'backend':p.compute_device_type,
'enabled':{d.name+':'+d.type:d.use for d in p.devices},'samples':bpy.context.scene.cycles.samples}
"""


def run(qa):
    out = Path(os.environ['QA_SCENARIO_OUT'])
    out.mkdir(parents=True, exist_ok=False)
    qa.eval(SETUP)
    before = qa.eval(DEVICE_SETTINGS)

    async def execute(code, tool, session):
        return await asyncio.to_thread(script, qa, code)

    async def verify():
        store = Store(fakeredis.aioredis.FakeRedis(decode_responses=True))
        box = ToolBox(store, SimpleNamespace(instance_id='qa-4817', execute=execute), 'qa-capabilities', True)
        try:
            info = json.loads(await box.call('get_system_info', {}))
            require(info['available'] and info['cpu_threads'] > 0, 'No system facts')
            require(qa.eval(DEVICE_SETTINGS) == before, 'Read-only probe changed settings')
            await box.call('inspect_scene', {})
            code = 'import bpy\ndef helper_cube(name, x):\n    bpy.ops.mesh.primitive_cube_add(size=.3, location=(x,0,.3))\n    bpy.context.object.name=name\n'
            await box.call('register_helpers', {'code': code})
            for n, x in [('Helper A', 2), ('Helper B', -2)]:
                result = json.loads(await box.call('execute_python', {'code': f'helper_cube({n!r}, {x})\n__RESULT__={{"built":{n!r}}}', 'inspect': True, 'notes': n}))
                require(result['inspection']['object_count'] >= 5, 'Combined inspection missing')
            try:
                await box.call('execute_python', {'code':'exec("bad")'})
            except ValidationError:
                pass
            else:
                raise AssertionError('Dynamic execution accepted')
            require(box.inspected, 'Validation rejection invalidated evidence')
            # Inspect >3000 objects and target one beyond the first detail page.
            qa.eval("\nfor i in range(3086):\n o=bpy.data.objects.new('Inspect_%04d'%i,None);bpy.context.scene.collection.objects.link(o)\nresult=True")
            summary = await box.call('inspect_scene', {})
            targeted = json.loads(await box.call('inspect_scene', {'names':['Inspect_3085']}))
            require(len(summary) < 12000, 'Default inspection is too large')
            require(targeted['objects'][0]['name']=='Inspect_3085', 'Named query missed tail object')
            result = await box.call('render_preview', {})
            details = json.loads(result[0]['text'])
            (out/'preview.jpg').write_bytes(base64.b64decode(result[1]['image_url'].split(',',1)[1]))
            require(box.inspected and box.previewed, 'Combined final evidence missing')
            report = details['render']
            if info['gpu']['devices']:
                require(report['device']=='GPU', 'Available GPU was not selected')
            else:
                require(report['device']=='CPU' and report['fallback_reason'], 'Missing CPU fallback reason')
            after = qa.eval(DEVICE_SETTINGS)
            require(after['device']==before['device'] and after['backend']==before['backend'] and after['samples']==before['samples'], 'Device settings did not restore')
            require(all(after['enabled'].get(n)==value for n,value in before['enabled'].items()), 'Enabled device flags changed')
            require(all(not value for n,value in after['enabled'].items() if n not in before['enabled']), 'Newly discovered devices stayed enabled')
            evidence={'system_info':info, 'preview':report, 'summary_chars':len(summary),
                      'object_count':targeted['object_count'], 'before':before,'after':after,
                      'helper_reuse':True,'validation_preserved_evidence':True}
            (out/'evidence.json').write_text(json.dumps(evidence,indent=2))
            return evidence
        finally:
            await store.redis.aclose()
    evidence = asyncio.run(verify())
    qa.snap(str(out/'completed.png'))
    return evidence


if __name__ == '__main__':
    run_scenario('agent_capabilities_e2e', run)
