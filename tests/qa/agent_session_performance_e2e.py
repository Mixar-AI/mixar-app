#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real-app session robustness/performance replay against a QA backend.

QA_HARNESS, MIXAR_QA_PORT, QA_SCENARIO_OUT and MIXAR_BACKEND_REPO are required.
Launch an isolated freshly built Dev app with MIXAR_QA=1. PHASE=native uses
no credits; PHASE=live sends three bounded modeling turns plus one preview
turn (ordinary model credits, no generation services). PHASE defaults to native.
PHASE=verify inspects the resulting live scene without sending another turn.
Transport and built client modules remain real during live turns. Timings are
observations, not a before/after benchmark. Inspect all emitted screenshots.
"""

import importlib.util
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ["QA_HARNESS"]) / "scenarios"))
from lib import QA

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ["QA_SCENARIO_OUT"]).resolve()


class IslandQA(QA):
    """Use the current island with older installed harness drivers."""

    def open_chat(self):
        # Hidden island windows retain semantic targets. The shortcut is
        # idempotent and restores them; find(input) alone cannot prove visibility.
        self.press("M", shift=True)
        self.wait("bool(drv.find(prop='mixie_chat_input'))", timeout=12)

    def install_compat(self):
        # Only navigation/query adaptation: chat_send still clicks, types and
        # presses Enter through the installed semantic event driver.
        return self.eval("""
import os
assert os.environ.get('MIXAR_QA') == '1'
if not hasattr(drv, '_perf_original_find'):
    drv._perf_original_find = drv.find
    def find(widgets=None, **query):
        if query.get('area_type') == 'MIXIE_CHAT':
            query['area_type'] = 'AGENT_BUBBLE'
        return drv._perf_original_find(widgets, **query)
    drv.find = find
    def ensure_chat_open():
        with bpy.context.temp_override(window=drv.main_window()):
            bpy.ops.mixar.open_mixie()
    drv.ensure_chat_open = ensure_chat_open
from mixar.config.config import get_server_url, get_environment
from mixar.modules.space_mixie_chat.core import preview_deferral
assert get_environment() == 'Dev'
assert get_server_url() == 'https://uat5.mixar.app'
from mixar.modules.onboarding.core.tour import session as tour
if tour.current(): tour.current().stop('qa')
from pathlib import Path
from mixar.modules.common.agent_history.core import store
from mixar.modules.space_mixie_chat.core import chat_history
out = Path(os.environ['MIXAR_QA_OUT'])
store.root = lambda: out / 'archive'
chat_history._mixar_home = lambda: str(out / 'chat')
chat_history.invalidate_cache()
from mixar.modules.byok.core import credential_state
credentials = credential_state.snapshot()
result = {'backend': get_server_url(), 'app_version': bpy.app.version_string,
          'blender_version': list(bpy.app.version),
          'byok_provider': credentials.get('byok_current_provider'),
          'byok_model': credentials.get('byok_current_model'),
          'client_module': preview_deferral.__file__}
""")

    def raw_chat_snap(self, filename):
        # Observe cached regions, without SCREEN_OT_screenshot's forced redraw
        # or stale Metal front-buffer reads. The island must already be visible.
        return self.eval(f"""
win = drv.find_one(prop='mixie_chat_input')['_win']
assert win.mixar_qa_capture_frame(filepath={str(OUT / filename)!r})
result = {str(OUT / filename)!r}
""")


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def native(qa):
    # Publication/geometry fixtures use exact backend templates. The client
    # sweep is the installed build; the existing replay's hotload is identical
    # source and its returned screenshot is retained for visual review.
    session = load_module(ROOT / "tests/qa/session_robustness_e2e.py", "session_replay")
    checks = session.run(qa)
    qa.eval(f"""
import importlib.util
spec = importlib.util.spec_from_file_location('perf_preview', {str(ROOT / 'tests/qa/preview_lifecycle_fixture.py')!r})
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
bpy.app.driver_namespace['perf_preview'] = fixture
result = fixture.setup(drv.main_window())
""")

    def call(expr):
        return qa.eval("f = bpy.app.driver_namespace['perf_preview']\nresult = " + expr)

    def finish(expected):
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            value = call("f.status()")
            if value["terminal"] and not value["native_running"] and not value["reserved"]:
                return call(f"f.finish({expected!r})")
            time.sleep(.25)
        raise AssertionError(f"Native preview did not settle: {value}")

    qa.step("preview_start", call, "f.start('complete', width=640, height=480)")
    qa.step("preview_running", call, "f.assert_running()")
    checks["preview_complete"] = qa.step("preview_complete", finish, "done")
    call("f.show_origin()")
    qa.open_chat()
    qa.raw_chat_snap("native-preview-completed.png")
    qa.eval("f = bpy.app.driver_namespace['perf_preview']\n"
            "f._bubble().images_collapsed = True\nresult=True")
    qa.step("cancel_start", call,
            "f.start('cancel', width=2048, height=1536, switch_tab=False)")
    qa.step("cancel_running", call, "f.assert_running()")
    qa.raw_chat_snap("native-preview-running.png")
    qa.step("native_stop", qa.click, text="Stop this job")
    checks["preview_cancelled"] = qa.step("preview_cancelled", finish, "cancelled")
    # Stop belongs to the host window: clicking it normally collapses the
    # island. Keep that cached observation, then verify the user-visible row
    # after its normal restore; a hidden buffer is not a stuck visible spinner.
    qa.raw_chat_snap("native-preview-cancelled-unforced.png")
    qa.open_chat()
    qa.raw_chat_snap("native-preview-cancelled-visible.png")
    call("f.release()")
    return checks


PROBE = """
scene = drv.main_window().scene
result = {
    'state': scene.mixie_chat_state, 'busy': scene.mixie_chat_is_busy,
    'session': scene.mixie_session_id,
    'messages': [{'sender': m.sender, 'text': m.text,
        'steps': [{'id': s.item_id, 'status': s.status, 'label': s.label,
                   'target': s.target, 'detail': s.detail} for s in m.step_items],
        'captures': [i.local_path for i in m.image_items]}
        for m in scene.mixie_chat_messages],
    'native_render': bpy.app.is_job_running('RENDER'),
    'lanes': [s.name for s in bpy.data.scenes
              if s.mixie_session_id.startswith('agentlane:')],
}
"""

PROMPTS = [
    ("simple", "Create a red cube named QA_PERF_CUBE, 2 metres on each side, "
     "centred at (-6, 0, 1). Use native Blender geometry. No questions, no "
     "generations, no preview needed. Keep existing objects."),
    ("parallel", "Build a small open pavilion from native primitives only. "
     "Use two parallel workers called pavilion_shell and pavilion_benches, "
     "each building in a private workspace; publish their results to MAIN. "
     "Shell: floor QA_PERF_FLOOR is 8 by 6 by 0.2 m, top at z=0; four "
     "0.3 m square columns rise from z=0 to z=3 at (+/-3, +/-2); roof is "
     "8 by 6 by 0.2 m with bottom at z=3. Benches: two wooden seats named "
     "QA_PERF_SEAT_A and QA_PERF_SEAT_B, 1.8 by 0.45 by 0.1 m, top at "
     "z=0.45, centres at (-1.5,0,0.4) and (1.5,0,0.4), four legs per "
     "seat extending from z=0 to z=0.35. Use flat simple materials. "
     "Preserve QA_PERF_CUBE and all existing objects. No external assets, "
     "no questions and no renders in this turn. Report the exact worker names."),
    ("followup", "Use followup_task to recover BOTH finished workers "
     "pavilion_shell and pavilion_benches from the previous run in this "
     "session. In the same tool round ask shell to recolor only the roof "
     "dark blue and benches to recolor only the two seats warm orange. "
     "Edit their existing objects in MAIN; do not rebuild, duplicate, or "
     "delete anything. Await both reports. Then use inspect_geometry to "
     "check rests_on between QA_PERF_SEAT_A and one of its legs at 0.005 m "
     "tolerance, and contact between QA_PERF_FLOOR and one column. If "
     "evidence is unavailable, report that explicitly; no repeated identical "
     "checks and no render yet."),
    ("preview", "Inspect the existing pavilion from the same scene, without "
     "changing its geometry. Set up a camera from (11,-14,9) aimed at "
     "(0,0,1), simple area lighting and a neutral world. Render exactly one "
     "small final Cycles preview with render_viewport, width 640 height 480, "
     "16 samples if supported. Wait for completion, assess it and report "
     "any remaining defect honestly. Do not generate assets, export files "
     "or launch additional corrective renders."),
]


def timed_turn(qa, name, prompt, timeout=600):
    before = qa.eval(PROBE)
    base = len(before["messages"])
    start = time.monotonic()
    qa.step(name + "_send", qa.chat_send, prompt)
    samples, first_response, active = [], None, False
    while time.monotonic() - start < timeout:
        sent = time.monotonic()
        state = qa.eval(PROBE)
        elapsed = time.monotonic() - start
        samples.append({'elapsed_s': round(elapsed, 3),
                        'probe_ms': round((time.monotonic() - sent) * 1000, 1),
                        'state': state['state'], 'busy': state['busy']})
        new = state["messages"][base:]
        if first_response is None and any(m["sender"] == "AGENT" and
                                         (m["text"] or m["steps"]) for m in new):
            first_response = round(elapsed, 3)
        active |= state["busy"] or state["state"] in {"BUSY", "MODIFYING"}
        (OUT / (name + '-progress.json')).write_text(json.dumps(state, indent=2))
        if state["state"] == "AWAITING_INPUT":
            raise AssertionError(f"Unexpected gate during {name}: {new[-1:]}")
        if active and not state["busy"] and state["state"] == "IDLE":
            completed = {'turn_seconds': round(elapsed, 3),
                    'first_response_seconds': first_response,
                    'max_probe_ms': max(s['probe_ms'] for s in samples),
                    'samples': samples, 'result': state}
            (OUT / (name + '-timings.json')).write_text(json.dumps(completed, indent=2))
            # Turn checkpoint saves close bubble windows. Reopen through the
            # normal shortcut only after measurement; native cancellation
            # screenshots deliberately never use this navigation path.
            qa.open_chat()
            qa.raw_chat_snap(name + '-transcript.png')
            return completed
        time.sleep(.5)
    raise AssertionError(f"{name} exceeded {timeout}s: {state['state']}")


def verify_scene(qa, *, recolored=True):
    """Assert geometry independently of agent prose; record output defects."""
    state = qa.eval("""
sc = drv.main_window().scene
assert sc.mixie_chat_state == 'IDLE' and not sc.mixie_chat_is_busy
assert not bpy.app.is_job_running('RENDER')
assert not [s for s in bpy.data.scenes if s.mixie_session_id.startswith('agentlane:')]
def close(actual, expected):
    assert all(abs(a-b) < .001 for a,b in zip(actual,expected)), (list(actual),expected)
def box(name, dimensions, location):
    o = sc.objects.get(name)
    assert o and o.type == 'MESH', name
    close(o.dimensions, dimensions)
    close(o.matrix_world.translation, location)
    return o
box('QA_PERF_CUBE', (2,2,2), (-6,0,1))
box('Cube', (2,2,2), (0,0,0))
assert 'Camera' in sc.objects and 'Light' in sc.objects
box('QA_PERF_FLOOR', (8,6,.2), (0,0,-.1))
box('QA_PERF_ROOF', (8,6,.2), (0,0,3.1))
columns = [o for o in sc.objects if o.name.startswith('QA_PERF_COLUMN_')]
assert len(columns) == 4
assert {(round(o.location.x),round(o.location.y)) for o in columns} == {(3,2),(3,-2),(-3,2),(-3,-2)}
for o in columns:
    close(o.dimensions, (.3,.3,3))
    assert abs(o.matrix_world.translation.z-1.5) < .001
for letter,x in [('A',-1.5),('B',1.5)]:
    name = 'QA_PERF_SEAT_' + letter
    box(name, (1.8,.45,.1), (x,0,.4))
    legs = [o for o in sc.objects if o.name.startswith(name+'_LEG_')]
    assert len(legs) == 4
    for o in legs:
        assert abs(o.dimensions.z-.35) < .001
        assert abs(o.matrix_world.translation.z-.175) < .001
meshes = [o for o in sc.objects if o.type == 'MESH']
assert len(meshes) == 18, [o.name for o in meshes]
def material(o):
    m = o.active_material
    assert m, o.name
    bsdf = next((n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'),None) if m.node_tree else None
    return {'name':m.name, 'diffuse':list(m.diffuse_color),
            'base_color':list(bsdf.inputs['Base Color'].default_value) if bsdf else None}
result = {
    'session':sc.mixie_session_id,
    'mesh_signature':{o.name:{'location':list(o.matrix_world.translation),
        'dimensions':list(o.dimensions),'vertices':len(o.data.vertices)} for o in meshes},
    'materials':{n:material(sc.objects[n]) for n in
        ['QA_PERF_CUBE','QA_PERF_ROOF','QA_PERF_SEAT_A','QA_PERF_SEAT_B']},
    'failed_steps':[{'id':s.item_id,'label':s.label,'detail':s.detail}
        for m in sc.mixie_chat_messages for s in m.step_items if s.status == 'FAILED'],
}
""")
    colors = {n: m['base_color'] or m['diffuse'] for n,m in state['materials'].items()}
    red = colors['QA_PERF_CUBE']
    checks = {'cube_shader_red': red[0] > .5 and red[1] < .1 and red[2] < .1,
              'no_failed_step_rows': not state['failed_steps']}
    if recolored:
        blue = colors['QA_PERF_ROOF']
        checks['roof_shader_blue'] = blue[2] > blue[0] and blue[2] > blue[1]
        for name in ('QA_PERF_SEAT_A', 'QA_PERF_SEAT_B'):
            orange = colors[name]
            checks[name + '_shader_orange'] = orange[0] > .5 and orange[0] > orange[1] > orange[2]
    state['quality_checks'] = checks
    state['quality_ok'] = all(checks.values())
    return state


def live(qa):
    qa.step("login", qa.cmd, "wait_login", timeout=60)
    qa.wait("drv.main_window().scene.mixie_chat_state == 'IDLE'", timeout=20)
    qa.open_chat()
    turns = {}
    signature = None
    verified = None
    start_at = os.environ.get('QA_START_AT', 'simple')
    started = False
    for name, prompt in PROMPTS:
        started |= name == start_at
        if not started:
            continue
        turns[name] = qa.step(name, timed_turn, qa, name, prompt)
        (OUT / 'live-partial.json').write_text(json.dumps(turns, indent=2))
        if name == 'simple':
            qa.eval("o = bpy.data.objects.get('QA_PERF_CUBE')\n"
                    "assert o and all(abs(d-2)<.001 for d in o.dimensions)\nresult=True")
        if name == 'parallel':
            verified = verify_scene(qa, recolored=False)
            signature = verified['mesh_signature']
        if name in {'followup', 'preview'}:
            verified = verify_scene(qa)
            if signature is not None:
                assert verified['mesh_signature'] == signature, 'Existing geometry changed or duplicated'
    scene = qa.eval("""
sc = drv.main_window().scene
result = {'objects': [{'name':o.name, 'type':o.type,
          'location':list(o.matrix_world.translation), 'dimensions':list(o.dimensions)}
          for o in sc.objects], 'session':sc.mixie_session_id}
""")
    qa.cmd('snap', path=str(OUT / 'live-scene.png'), area='VIEW_3D')
    return {'turns': turns, 'scene': scene, 'verification': verified,
            'quality_ok': verified['quality_ok'] if verified else True}


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    qa = IslandQA()
    phase = os.environ.get('PHASE', 'native')
    verdict = {'phase': phase, 'ok': False, 'state_assertions_ok': False,
               'visual_review_required': True}
    try:
        verdict['build'] = qa.step('island_compat', qa.install_compat)
        verdict['checks'] = {'native': native, 'live': live, 'verify': verify_scene}[phase](qa)
        verdict['state_assertions_ok'] = True
        verdict['ok'] = verdict['checks'].get('quality_ok', True)
    except Exception as exc:
        verdict['failure'] = str(exc)
    verdict['steps'] = qa.log
    (OUT / (phase + '-verdict.json')).write_text(json.dumps(verdict, indent=2))
    print(json.dumps({k:v for k,v in verdict.items() if k != 'checks'}, indent=2))
    raise SystemExit(0 if verdict['ok'] else 1)
