# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Replay a modelling prompt against an isolated Dev GUI.

One billed agent turn. For the watch, supply references in finished, exploded,
drawing order. Paths are local to the GUI host/container. The test
records responsiveness without cancelling or replaying a timed-out generation.
It does not equate valid geometry with photorealistic/mechanical correctness;
review the screenshots and final agent text separately.
"""
import argparse
import json
from pathlib import Path
import sys
import time


HEARTBEAT = """
import time
state={'last':time.monotonic(), 'max_gap':0.0, 'ticks':0, 'running':True, 'gaps':[]}
def tick(state=state, clock=time.monotonic, wall=time.time):
    if not state['running']:return None
    now=clock(); gap=now-state['last']
    state['max_gap']=max(state['max_gap'],gap)
    if gap>.25 and len(state['gaps'])<500:
        state['gaps'].append({'seconds':gap,'at_epoch':wall()})
    state['last']=now; state['ticks']+=1
    return .02
bpy.app.driver_namespace['_qa_full_watch_heartbeat']=state
bpy.app.timers.register(tick, first_interval=.02)
result=True
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--prompt', type=Path)
    source.add_argument('--case', help='Name in modeling_prompt_cases.json')
    parser.add_argument('--references', nargs='*', type=Path, default=[])
    parser.add_argument('--attachment-mode', choices=['drop', 'operator'], default='drop')
    parser.add_argument('--scene', default='QA_Full_Watch')
    parser.add_argument('--harness', type=Path, required=True)
    parser.add_argument('--port', type=int, default=4777)
    parser.add_argument('--out', type=Path, default=Path('/tmp/watch-full-e2e'))
    parser.add_argument('--timeout', type=float, default=3600)
    parser.add_argument('--observe', action='store_true')
    args = parser.parse_args()
    sys.path.insert(0, str(args.harness / 'scenarios'))
    from lib import QA
    qa = QA(port=args.port)
    args.out.mkdir(parents=True, exist_ok=True)
    provenance = None
    if args.case:
        cases = json.loads(Path(__file__).with_name('modeling_prompt_cases.json').read_text())
        provenance = next(case for case in cases if case['name'] == args.case)
        prompt = provenance['prompt']
    else:
        prompt = args.prompt.read_text()
    prompt = ' '.join(prompt.split())
    assert all(p.is_file() for p in args.references)
    assert qa.eval("import os; result=os.environ.get('MIXAR_QA')=='1'")
    assert qa.eval("from mixar.config.config import get_server_url; result=get_server_url()") == args.backend
    run_path = args.out / 'run.json'
    if not args.observe:
        status = qa.status()
        assert status['logged_in'] and status['state'] == 'IDLE' and not status['busy'], status
        qa.eval("scene_name=" + repr(args.scene) + "\n" + """
from mixar.modules.space_mixie_chat.ui.operators.scene_tab_ops import new_scene_tab
assert bpy.data.scenes.get(scene_name) is None, 'Use a fresh test scene'
w=drv.main_window()
with bpy.context.temp_override(window=w):
    new_scene_tab(scene_name)
result=True
""")
        target = {'prop':'mixie_chat_input', 'area_type':'AGENT_BUBBLE'}
        # Save recreates companion windows asynchronously. Wait for the actual
        # surface before opening it; opening and clicking during restoration
        # can toggle the new island closed again.
        qa.wait("bool(drv.find(surface='pill_cat') or "
                "drv.find(prop='mixie_chat_input', area_type='AGENT_BUBBLE'))", timeout=8)
        if not qa.find(**target)['total']:
            qa.click(surface='pill_cat')
        qa.wait("bool(drv.find(prop='mixie_chat_input', area_type='AGENT_BUBBLE'))", timeout=5)
        for index, path in enumerate(args.references, 1):
            if args.attachment_mode == 'operator':
                # The same operator the paperclip file picker executes. Some
                # X11 harness builds do not deliver simulated file-drop events.
                qa.eval("w=drv.main_window()\nwith bpy.context.temp_override(window=w):\n"
                        "    status=bpy.ops.mixie_chat.add_image_from_file(filepath="
                        + repr(str(path.resolve())) + ")\nassert 'FINISHED' in status\nresult=True")
            else:
                qa.cmd('drop_file', target=target, path=str(path.resolve()))
            assert qa.eval('result=len(drv.main_window().scene.mixie_chat_pending_attachments)') == index
        qa.cmd('set_text', widget=target, text=prompt, enter=False)
        assert qa.eval('result=drv.main_window().scene.mixie_chat_input') == prompt
        qa.eval(HEARTBEAT)
        run = {'sent_at_epoch':time.time(), 'backend':args.backend,
               'scene':args.scene, 'case':provenance,
               'references':[p.name for p in args.references]}
        run_path.write_text(json.dumps(run, indent=2))
        qa.click(op='MIXIE_CHAT_OT_send_message')
    else:
        run = json.loads(run_path.read_text())
    assert qa.eval("result=next((m.text for m in drv.main_window().scene.mixie_chat_messages "
                   "if m.sender=='USER'),'')") == prompt
    assert qa.eval('result=drv.main_window().scene.name') == run['scene']
    (args.out / 'prompt.txt').write_text(prompt + '\n')
    with (args.out / 'progress.jsonl').open('a', buffering=1) as output:
        while time.time() - run['sent_at_epoch'] < args.timeout:
            before = time.monotonic()
            record = {'at_epoch':time.time(), 'elapsed':time.time()-run['sent_at_epoch']}
            try:
                record.update(qa.cmd('status', _sock_timeout=5))
            except Exception as exc:
                record['error'] = str(exc)
            record['roundtrip'] = time.monotonic() - before
            output.write(json.dumps(record) + '\n')
            (args.out / 'latest.json').write_text(json.dumps(record, indent=2))
            if record.get('error'):
                print('PROBE_TIMEOUT', json.dumps(record), flush=True)
            if record.get('state') == 'AWAITING_INPUT':
                raise RuntimeError('Choice gate reached; left active for inspection')
            if record.get('state') == 'IDLE' and not record.get('busy'):
                break
            time.sleep(2)
        else:
            raise TimeoutError('Generation still running; left active without cancellation')
    # End the generation heartbeat BEFORE geometry validation, capture or save.
    completed_at = time.time()
    heartbeat = qa.eval("s=bpy.app.driver_namespace['_qa_full_watch_heartbeat']\n"
                        "s['running']=False\nresult=s")
    result = qa.cmd('eval', code="""
from mixar.modules.space_mixie_chat.core.connection_manager import get_connection_manager
s=drv.main_window().scene
meshes={o.data.name:o.data for o in s.objects if o.type=='MESH'}
invalid=[]
for mesh in meshes.values():
    copy=mesh.copy()
    try:
        if copy.validate(clean_customdata=False):invalid.append(mesh.name)
    finally:
        bpy.data.meshes.remove(copy)
result={'session':s.mixie_session_id, 'scene':s.name,
        'connected':bool(get_connection_manager().is_connected),
        'objects':[{'name':o.name,'type':o.type} for o in s.objects],
        'unique_meshes':len(meshes), 'invalid_meshes':invalid,
        'vertices':sum(len(m.vertices) for m in meshes.values()),
        'faces':sum(len(m.polygons) for m in meshes.values()),
        'camera':s.camera.name if s.camera else None,
        'agent_text':next((m.text for m in reversed(s.mixie_chat_messages)
                          if m.sender=='AGENT' and m.text),''),
        'transcript':[{'sender':m.sender,'type':m.message_type,'text':m.text}
                      for m in s.mixie_chat_messages if m.text]}
""", _sock_timeout=60)
    records = [json.loads(line) for line in (args.out / 'progress.jsonl').read_text().splitlines()]
    result.update(heartbeat=heartbeat, elapsed=completed_at-run['sent_at_epoch'],
                  probe_failures=sum('error' in r for r in records),
                  max_probe_seconds=max(r['roundtrip'] for r in records))
    (args.out / 'verdict.json').write_text(json.dumps(result, indent=2))
    qa.cmd('snap', path=str(args.out / 'final-viewport.png'), area='VIEW_3D')
    scene_path = str(args.out / 'scene.mixar')
    qa.eval(f"result=str(bpy.ops.wm.save_as_mainfile(filepath={scene_path!r},copy=True))")
    assert result['connected'] and result['unique_meshes'] and not result['invalid_meshes'], result
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()
