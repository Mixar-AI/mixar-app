#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Start, edit while rendering, collect old pixels, then verify current pixels."""
import asyncio
import base64
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
sys.path.insert(0, os.environ['MIXAR_BACKEND'])
from lib import run_scenario
from async_preview_e2e import SETUP, require, script
import fakeredis.aioredis
from modules.agent_next.state import Store
from modules.agent_next.tools import ToolBox


def run(qa):
    out = Path(os.environ['QA_SCENARIO_OUT'])
    out.mkdir(parents=True, exist_ok=False)
    qa.eval(SETUP)
    async def execute(code, tool, session):
        return await asyncio.to_thread(script, qa, code)
    async def verify():
        store = Store(fakeredis.aioredis.FakeRedis(decode_responses=True))
        box = ToolBox(store, SimpleNamespace(instance_id='qa-overlap', execute=execute), 'qa-overlap-chat', True)
        try:
            await box.call('inspect_scene', {})
            t = time.monotonic()
            job = json.loads(await box.call('start_render_preview', {}))
            start_seconds = time.monotonic() - t
            require(job['status']=='running', 'Start waited for completion')
            require(qa.eval("result=bpy.app.is_job_running('RENDER')"), 'No native render overlaps edit')
            t = time.monotonic()
            await box.call('execute_python', {'code':"import bpy\nbpy.ops.mesh.primitive_cube_add(size=.5, location=(1.8,0,.3))\nbpy.context.object.name='Overlap_New_Cube'\n__RESULT__={'created': 'Overlap_New_Cube'}", 'inspect':True})
            edit_seconds = time.monotonic() - t
            result = await box.call('get_render_preview', {'job_id':job['job_id'], 'wait':True})
            progress = json.loads(result[0]['text'])
            require(progress['scene_advanced'] and not box.previewed, 'Older image verified newer edits')
            (out/'progress.jpg').write_bytes(base64.b64decode(result[1]['image_url'].split(',',1)[1]))
            require(qa.eval("result='Overlap_New_Cube' in bpy.context.scene.objects"), 'Edit was lost')
            final_job = json.loads(await box.call('start_render_preview', {}))
            final_result = await box.call('get_render_preview', {'job_id':final_job['job_id'], 'wait':True})
            final = json.loads(final_result[0]['text'])
            require(final['usable_for_final_verification'] and box.previewed, 'Fresh render did not verify')
            (out/'final.jpg').write_bytes(base64.b64decode(final_result[1]['image_url'].split(',',1)[1]))
            # Local user edit after collecting pixels must prevent final completion.
            qa.eval("bpy.data.objects['Overlap_New_Cube'].location.x += .2; result=True")
            await box.refresh_preview_evidence()
            require(not box.previewed, 'Later UI edit escaped final check')
            report={'start_seconds':start_seconds,'edit_seconds':edit_seconds,'progress':progress,'final':final,'later_ui_edit_invalidated_final':True,'provider_calls':0}
            (out/'evidence.json').write_text(json.dumps(report,indent=2))
            return {'start_seconds':start_seconds, 'edit_seconds':edit_seconds, 'progress_retained':True, 'fresh_final_verified':True, 'later_ui_edit_detected':True}
        finally:
            await store.redis.aclose()
    result = asyncio.run(verify())
    qa.snap(str(out/'completed.png'))
    return result


if __name__ == '__main__':
    run_scenario('agent_preview_overlap_e2e', run)
