# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Replay the full backend chat path with e2e_backend.py --scripted-agent.

Uses the real Dev app, normal agent commands, graph, prompt loader and skill
middleware. The backend replaces only model responses. No provider calls.
"""

import argparse
import asyncio
import base64
import json
from pathlib import Path
from uuid import uuid4

from mcp import Client, StdioServerParameters
from e2e_scene import load_qa, enable_in_ui


async def run(options):
    out = options.fixture / 'agent-evidence'
    out.mkdir(exist_ok=True)
    qa = load_qa(options.qa_harness, options.qa_port)
    for _ in range(90):
        try:
            qa.status()
            break
        except OSError:
            await asyncio.sleep(0.5)
    qa.cmd('wait_login', timeout=90)
    expected = json.loads((options.fixture / 'fixture.json').read_text())['backend_url']
    info = qa.eval("from mixar.config.config import get_server_url; from mixar.modules.mcp_bridge.core.runtime import enabled; import os; result={'backend':get_server_url(),'enabled':enabled(),'qa':os.environ.get('MIXAR_QA')}")
    assert info['qa'] == '1' and info['backend'] == expected and expected.startswith('http://127.0.0.1:')
    if not info['enabled']:
        await asyncio.to_thread(enable_in_ui, qa, out)
    server = StdioServerParameters(command=str(options.python), args=[str(options.launcher)],
        env={'MIXAR_MCP_DISCOVERY_DIR': str(options.fixture / 'discovery')})
    async with Client(server, mode='legacy', read_timeout_seconds=120) as client:
        cid = str(uuid4())
        args = {'text': 'ASK_QA: Build a blue beveled test block beside the existing cube. Ask which finish first. Preserve existing objects.'}
        first = await client.call_tool('mixar_agent_start', args, meta={'mixar/request-id': cid})
        assert not first.is_error, first
        assert first.structured_content['result']['command_id'] == cid
        duplicate = await client.call_tool('mixar_agent_start', args, meta={'mixar/request-id': cid})
        assert duplicate.structured_content['result']['replayed']
        states = []
        for _ in range(90):
            result = await client.call_tool('mixar_agent_status', {'command_id': cid})
            value = result.structured_content['result']
            state = value.get('state')
            if not states or states[-1] != state:
                states.append(state)
                print(json.dumps({'state': state}), flush=True)
            if state == 'waiting_for_input':
                question = value['questions'][-1]
                assert question['interrupt_id'] and question['options'], question
                stale = await client.call_tool('mixar_agent_respond', {'command_id': cid, 'text': 'Blue', 'interrupt_id': 'stale-question'})
                assert stale.is_error
                response = await client.call_tool('mixar_agent_respond', {'command_id': cid, 'text': 'Blue', 'interrupt_id': question['interrupt_id']})
                assert not response.is_error, response
                cid = response.structured_content['result']['command_id']
            if state == 'finished':
                break
            assert not result.is_error and state not in ('failed', 'unavailable'), value
            await asyncio.sleep(1)
        else:
            raise AssertionError({'timeout': True, 'last_status': value})
        assert any('MCP_AGENT_QA' in m for m in value['messages']), value
        facts = qa.eval("o=bpy.data.objects.get('MCP_AGENT_QA'); result={'exists':o is not None, 'count':sum(x.name.startswith('MCP_AGENT_QA') for x in bpy.data.objects), 'vertices':len(o.data.vertices) if o else 0, 'bevel_segments':o.modifiers[0].segments if o else 0, 'stock_cube':bpy.data.objects.get('Cube') is not None, 'busy':drv.main_window().scene.mixie_chat_is_busy}")
        assert facts == {'exists': True, 'count': 1, 'vertices': 8, 'bevel_segments': 3, 'stock_cube': True, 'busy': False}, facts
        audit = json.loads((options.fixture / 'prompt-audit.json').read_text())
        assert audit == {'real_system_prompt': True, 'skill_in_system_message': True}
        capture = await client.call_tool('render_viewport', {'view': 'hero', 'focus_objects': ['MCP_AGENT_QA'], 'include_touching': False, 'width': 1024, 'height': 768, 'quality': 'fast'})
        images = [b for b in capture.content if b.type == 'image']
        assert images and not capture.is_error
        for i, block in enumerate(images):
            (out / f'viewport-{i}.jpg').write_bytes(base64.b64decode(block.data))
        qa.press('HOME')
        await asyncio.sleep(0.5)
        qa.cmd('snap', path=str(out / 'desktop.png'))
        second = await client.call_tool('mixar_agent_start', args)
        assert not second.is_error, second
        cancel_id = second.structured_content['result']['command_id']
        for _ in range(45):
            status = await client.call_tool('mixar_agent_status', {'command_id': cancel_id})
            if status.structured_content['result'].get('state') == 'waiting_for_input':
                break
            await asyncio.sleep(1)
        else:
            raise AssertionError('Second task did not pause for cancellation')
        cancelled = await client.call_tool('mixar_agent_cancel', {'command_id': cancel_id})
        assert not cancelled.is_error, cancelled
        for _ in range(30):
            status = await client.call_tool('mixar_agent_status', {'command_id': cancel_id})
            if status.structured_content['result'].get('state') == 'cancelled':
                break
            await asyncio.sleep(1)
        else:
            raise AssertionError('Cancellation unconfirmed')
        qa.wait('not drv.main_window().scene.mixie_chat_is_busy', timeout=10)
        assert qa.eval("result=sum(x.name.startswith('MCP_AGENT_QA') for x in bpy.data.objects)") == 1
        verdict = {'ok': True, 'states': states, 'duplicate_prevented': True, 'question_resume_and_cancel': True,
                   'scene': facts, 'prompt_audit': audit, 'provider': 'deterministic fixture; no live model quality claim'}
        (out / 'verdict.json').write_text(json.dumps(verdict, indent=2))
        print(json.dumps(verdict), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--qa-harness', type=Path, required=True)
    parser.add_argument('--qa-port', type=int, default=4798)
    parser.add_argument('--python', type=Path, required=True)
    parser.add_argument('--launcher', type=Path, required=True)
    asyncio.run(run(parser.parse_args()))
