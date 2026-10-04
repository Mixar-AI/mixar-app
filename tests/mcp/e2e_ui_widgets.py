# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Credit-free native UI checks after e2e_ui_control.py in its isolated fixture.

Tests menu replay/recovery, numeric text, enum choice and viewport gestures.
Harness reads independent state; every tested action uses the installed MCP.
Writes per-case verdicts even on failure and restores fixture render settings.
"""
import argparse
import asyncio
import base64
import json
import os
from pathlib import Path
from uuid import uuid4

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from e2e_scene import load_qa


async def run(options):
    root = options.fixture
    qa = load_qa(options.harness, options.port)
    facts = qa.eval("from mixar.config.config import get_server_url; "
                    "result={'normal':not bpy.app.use_event_simulate, "
                    "'qa':__import__('os').environ.get('MIXAR_QA')=='1', "
                    "'backend':get_server_url()}")
    assert facts['normal'] and facts['qa'] and facts['backend'].startswith(
        'http://127.0.0.1:'), facts
    original = qa.eval("result={'engine':drv.main_window().scene.render.engine,"
                       "'samples':drv.main_window().scene.eevee.taa_render_samples}")
    params = StdioServerParameters(command=str(root / 'connector/mixar-mcp'), args=[],
        env={**os.environ, 'MIXAR_MCP_DISCOVERY_DIR': str(root / 'discovery')})
    verdict = {'cases': {}, 'normal_input': True}
    async with stdio_client(params) as streams:
        async with ClientSession(*streams) as client:
            await client.initialize()

            async def call(tool, args, identity=None):
                result = await client.call_tool(tool, args,
                    meta={'mixar/request-id': identity or str(uuid4())})
                assert not result.is_error, str(result.content)
                return result

            async def observe(query=None, picture=None):
                args = {'limit': 200, 'image': bool(picture)}
                if query:
                    args['query'] = query
                result = await call('mixar_ui_observe', args)
                if picture:
                    image = next(b for b in result.content if b.type == 'image')
                    (root / picture).write_bytes(base64.b64decode(image.data))
                return result.structured_content['result']

            async def act(query, action, **args):
                state = await observe(query)
                assert len(state['targets']) == 1, state['targets']
                return await call('mixar_ui_act', {'context': state['context'],
                    'target': state['targets'][0]['target'], 'action': action, **args})

            async def escape():
                state = await observe()
                popup = next((w for w in state['targets'] if w.get('popup')), None)
                target = popup or next(r for r in state['regions'] if
                    r['area_type'] == 'VIEW_3D' and r['region_type'] == 'WINDOW')
                await call('mixar_ui_act', {'context': state['context'],
                    'target': target['target'], 'action': 'press', 'key': 'ESC'})

            async def menu():
                state = await observe({'text': 'Help'})
                assert len(state['targets']) == 1
                args = {'context': state['context'], 'target': state['targets'][0]['target'],
                        'action': 'click'}
                identity = str(uuid4())
                await call('mixar_ui_act', args, identity)
                first = await observe(picture='widgets-help.png')
                assert any(t.get('popup') for t in first['targets'])
                replay = await call('mixar_ui_act', args, identity)
                assert replay.structured_content['result']['replayed']
                assert any(t.get('popup') for t in (await observe())['targets'])
                verdict['menu_call_id'] = identity
                await escape()
                assert not any(t.get('popup') for t in (await observe())['targets'])

            async def numeric():
                await act({'prop': 'taa_render_samples'}, 'set_text', text='32')
                actual = qa.eval('result=drv.main_window().scene.eevee.taa_render_samples')
                await observe(picture='widgets-numeric.png')
                assert actual == 32, {'expected': 32, 'actual': actual}

            async def dropdown():
                await act({'prop': 'engine'}, 'choose', item='Workbench')
                actual = qa.eval('result=drv.main_window().scene.render.engine')
                await observe(picture='widgets-dropdown.png')
                assert actual == 'BLENDER_WORKBENCH', actual

            async def gesture():
                expression = "result=[v for row in next(a for a in drv.main_window().screen.areas if a.type=='VIEW_3D').spaces.active.region_3d.view_matrix for v in row]"
                before = qa.eval(expression)
                state = await observe()
                region = next(r for r in state['regions'] if
                    r['area_type'] == 'VIEW_3D' and r['region_type'] == 'WINDOW')
                await call('mixar_ui_act', {'context': state['context'], 'target': region['target'],
                    'action': 'gesture', 'button': 'MIDDLEMOUSE', 'duration': 0.5,
                    'points': [[0.5, 0.5], [0.55, 0.52], [0.6, 0.55]]})
                after = qa.eval(expression)
                await observe(picture='widgets-gesture.png')
                assert before != after, 'Viewport view matrix did not change'

            for name, test in [('menu_replay', menu), ('numeric_text', numeric),
                               ('enum_choice', dropdown), ('viewport_gesture', gesture)]:
                try:
                    await test()
                    verdict['cases'][name] = {'ok': True}
                except Exception as exc:
                    verdict['cases'][name] = {'ok': False, 'error': str(exc)}
                    await escape()
                (root / 'widgets-verdict.json').write_text(json.dumps(verdict, indent=2))
            await call('mixar_ui_context', {'release': True})
    # A new launcher must recover an already-completed local action without input.
    if verdict.get('menu_call_id'):
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as client:
                await client.initialize()
                recovered = await client.call_tool('mixar_ui_call_status',
                    {'call_id': verdict['menu_call_id']})
                content = recovered.structured_content or {}
                verdict['receipt_after_launcher_restart'] = {
                    'ok': not recovered.is_error and
                          content.get('result', {}).get('status') == 'succeeded',
                    'result': content}
    qa.eval(f"s=drv.main_window().scene; s.render.engine={original['engine']!r}; "
            f"s.eevee.taa_render_samples={original['samples']}; result=True")
    verdict['ok'] = all(case['ok'] for case in verdict['cases'].values()) and bool(
        verdict.get('receipt_after_launcher_restart', {}).get('ok'))
    (root / 'widgets-verdict.json').write_text(json.dumps(verdict, indent=2))
    print(json.dumps(verdict, indent=2))
    if not verdict['ok']:
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--harness', type=Path, required=True)
    parser.add_argument('--port', type=int, default=4827)
    asyncio.run(run(parser.parse_args()))
