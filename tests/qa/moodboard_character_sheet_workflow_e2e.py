#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit Character Sheet to 3D workflow template with a rich catalog fixture.

Drags the real "Character Sheet to 3D" shortcut onto a sheet still, checks the
framed draft graph (cards, labels, links, Assemble rows, frame membership and
reveal), undoes it with one Ctrl+Z, repeats without Auto Rig, and confirms the
+ menu hides the entry once the image model publishes no reference limit.
The catalog fixture replaces only the in-memory snapshot and is restored; no
Generate is pressed and no job can be queued. Set QA_HARNESS, MIXAR_QA_PORT,
QA_SCENARIO_OUT; use a clean isolated QA app. Inspect the screenshots.
"""

import json
import sys

from moodboard_drawer_e2e import OUT, SCENE, require, run_scenario

ADD = 'MIXIE_OT_moodboard_add_template'
MENU = 'Start with an editable node template'
LABEL = 'Character Sheet to 3D'
UNDO = {'oskey': True} if sys.platform == 'darwin' else {'ctrl': True}
IMAGE_SPEC = {'inputs': [{'kind': 'image', 'name': 'reference_images', 'multiple': True}],
              'cost_multiplier_param': 'number_of_images'}
IMAGE_MODEL = {'slug': 'qa', 'label': 'QA image', 'is_default': True, 'max_reference_images': 4,
               'parameters': {'number_of_images': {'type': 'integer', 'default': 2,
                                                   'min': 1, 'max': 4}}}


def capability(key, service, models, **overrides):
    record = {'key': service, 'label': service, 'surface': 'moodboard', 'models': models}
    record.update(overrides)
    return {'key': key, 'label': key, 'services': [record]}


def rich_catalog(rig=True, max_refs=True):
    image = dict(IMAGE_MODEL)
    if not max_refs:
        image.pop('max_reference_images')
    capabilities = [
        capability('image_gen', 'image_gen', [image], input_spec=IMAGE_SPEC),
        capability('model_gen', 'image_to_3d',
                   [{'slug': 'qa3d', 'label': 'QA 3D', 'is_default': True, 'parameters': {}}],
                   input_spec={'inputs': [{'kind': 'image', 'name': 'image'}]}),
    ]
    if rig:
        capabilities.append(capability(
            'animate', 'animate', [{'slug': 'qa-rig', 'label': 'QA rig', 'parameters': {}}]))
    return capabilities


def fixture(qa, capabilities):
    qa.eval(f'''
from mixar.bootstrap import generation_catalog_cache as catalog
with catalog._lock:
    catalog._catalog={{'capabilities':{capabilities!r}}}
    catalog._bump_enum_version_locked()
catalog._on_catalog_swapped()
area=next(a for a in drv.main_window().screen.areas if a.type=='MIXIE')
area.tag_redraw()
result=True
''')


def capture(qa, name):
    qa.cmd('snap', path=str(OUT / f'{name}.png'))


def sheet_point(qa):
    """Screen point at the centre of the sheet still."""
    return qa.eval(f'''
from mixar.modules.moodboard.core.frames import item_rect
win=drv.main_window()
area=next(a for a in win.screen.areas if a.type=='MIXIE')
region=next(r for r in area.regions if r.type=='WINDOW')
left,bottom,right,top=item_rect({SCENE}.mixie_moodboard_images[0])
p=region.view2d.view_to_region((left+right)/2,(bottom+top)/2,clip=False)
result={{'x':round(p[0]+region.x),'y':round(p[1]+region.y)}}
''')


def graph(qa):
    return qa.eval(f'''
from mixar.modules.moodboard.core.frames import frame_members
scene={SCENE}
win=drv.main_window()
area=next(a for a in win.screen.areas if a.type=='MIXIE')
region=next(r for r in area.regions if r.type=='WINDOW')
frames=list(scene.mixie_moodboard_frames)
frame=frames[0] if frames else None
def on_screen(x,y):
    p=region.view2d.view_to_region(x,y,clip=False)
    return 0<=p[0]<=region.width and 0<=p[1]<=region.height
def value(node,name):
    p=next((p for p in node.parameters if p.name==name),None)
    return None if p is None else (p.value_integer if p.parameter_type=='INTEGER' else p.value_enum)
result={{
  'cards':[{{'id':n.node_id,'type':n.action_type,'label':n.label,'state':n.state,
             'job':n.job_id,'requires':n.requires_reference,'prompt':n.prompt[:40],
             'count':value(n,'number_of_images'),'slot0':value(n,'slot:0'),
             'slot1':value(n,'slot:1'),'frame':n.frame_id}}
           for n in scene.mixie_moodboard_action_nodes],
  'links':sorted([l.from_node_id,l.to_node_id,l.to_socket] for l in scene.mixie_moodboard_links),
  'notes':[t.frame_id for t in scene.mixie_moodboard_textboxes],
  'sheet':{{'id':scene.mixie_moodboard_images[0].node_id,
            'frame':scene.mixie_moodboard_images[0].frame_id,
            'at':[scene.mixie_moodboard_images[0].position_x,
                  scene.mixie_moodboard_images[0].position_y]}},
  'frames':len(frames),
  'frame':None if frame is None else {{'id':frame.frame_id,'name':frame.name,
      'members':len(frame_members(scene,frame.frame_id)),
      'revealed':on_screen(frame.position_x,frame.position_y)
                 and on_screen(frame.position_x+frame.width,frame.position_y+frame.height)}},
}}
''')


def drop_workflow(qa, rig):
    before = graph(qa)
    require(not before['cards'] and not before['frames'], f'Use a clean board: {before}')
    shortcut = [w for w in qa.find(op=ADD, text=LABEL, area_type='MIXIE')['widgets']
                if w.get('block', '').startswith('MIXIE_PT_canvas_templates')]
    require(shortcut, 'The Character Sheet to 3D shortcut is not on the canvas strip')
    qa.cmd('drag', **{'from': {'op': ADD, 'text': LABEL, 'area_type': 'MIXIE',
                               'region_type': 'WINDOW'},
                     'to': sheet_point(qa), 'steps': 18})
    qa.wait(f'len({SCENE}.mixie_moodboard_frames)==1', timeout=10)
    state = graph(qa)
    cards = state['cards']
    by_type = {kind: [c for c in cards if c['type'] == kind]
               for kind in ('IMAGE_GEN', 'MODEL_3D', 'AUTO_RIG', 'ASSEMBLE')}
    counts = [len(by_type[kind]) for kind in ('IMAGE_GEN', 'MODEL_3D', 'AUTO_RIG', 'ASSEMBLE')]
    require(counts == [3, 3, 1 if rig else 0, 1], f'Wrong cards: {counts}')
    refs, m3d = by_type['IMAGE_GEN'], by_type['MODEL_3D']
    require([c['label'] for c in refs] == ['Body', 'Right-hand item', 'Left-hand item'],
            f'Wrong reference labels: {refs}')
    require(all(c['prompt'].startswith(c['label']) for c in refs), f'Prompts: {refs}')
    require(all(c['requires'] and c['count'] == 1 for c in refs),
            f'References must require the sheet and make one image: {refs}')
    require(all(c['state'] == 'DRAFT' and not c['job'] for c in cards), f'Submitted: {cards}')
    assemble = by_type['ASSEMBLE'][0]
    require(assemble['label'] == 'Assemble' and (assemble['slot0'], assemble['slot1'])
            == ('HAND_R', 'HAND_L'), f'Assemble rows: {assemble}')
    links = {tuple(link) for link in state['links']}
    sheet = state['sheet']['id']
    expected = {(sheet, c['id'], 'reference_images:0') for c in refs}
    expected |= {(r['id'], m['id'], 'image') for r, m in zip(refs, m3d)}
    body = m3d[0]['id']
    if rig:
        rig_card = by_type['AUTO_RIG'][0]
        require(rig_card['label'] == 'Rig Body', f'Rig label: {rig_card}')
        expected.add((body, rig_card['id'], 'mesh'))
        body = rig_card['id']
    expected |= {(body, assemble['id'], 'body'), (m3d[1]['id'], assemble['id'], 'parts:0'),
                 (m3d[2]['id'], assemble['id'], 'parts:1')}
    require(links == expected, f'Wrong links: {sorted(links ^ expected)}')
    frame = state['frame']
    require(frame['members'] == len(cards) + 1 and state['notes'] == [frame['id']],
            f'Frame must hold every card and the note: {state}')
    require(not state['sheet']['frame'] and state['sheet']['at'] == before['sheet']['at'],
            f'The sheet must stay put, outside the frame: {state["sheet"]}')
    require(frame['revealed'], f'The dropped workflow was not revealed: {frame}')
    return state


def undo_once(qa):
    qa.press('Z', **UNDO)
    qa.wait(f'len({SCENE}.mixie_moodboard_frames)==0', timeout=5)
    state = graph(qa)
    require(not state['cards'] and not state['links'] and not state['notes'],
            f'One undo must remove the whole workflow: {state}')
    return state


def menu_hides_workflow(qa):
    qa.click(text=MENU)
    texts = {w['text'] for w in qa.find(op=ADD, popup=True)['widgets']}
    require('Generate Image' in texts and LABEL not in texts,
            f'Without a reference limit the workflow must be hidden: {texts}')
    capture(qa, '05-menu-without-reference-limit')
    qa.press('ESC')
    return sorted(texts)


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    require(qa.eval("result=__import__('os').environ.get('MIXAR_QA')=='1'"), 'Use an isolated QA app')
    qa.cmd('wait_login', timeout=90)
    qa.dismiss_splash()
    qa.cmd('ensure_moodboard', sidebar=False)
    qa.eval(f'''
from mixar.bootstrap import generation_catalog_cache as catalog
bpy.app.driver_namespace['_qa_sheet_catalog']=catalog._catalog
win=drv.main_window()
area=next(a for a in win.screen.areas if a.type=='MIXIE')
region=next(r for r in area.regions if r.type=='WINDOW')
image=bpy.data.images.new('QA Warrior Sheet', width=96, height=64)
image.generated_color=(.55,.35,.2,1)
image.pack()
item={SCENE}.mixie_moodboard_images.add()
item.image=image
item.node_id='qa-warrior-sheet'
item.scale=.6
x,y=region.view2d.region_to_view(region.width*.2,region.height*.5)
item.position_x=x
item.position_y=y
# The sheet is fixture state: record it so the workflow's Ctrl+Z stops here.
with bpy.context.temp_override(window=win,area=area,region=region):
    bpy.ops.ed.undo_push(message='QA sheet')
area.tag_redraw()
result=True
''')
    try:
        fixture(qa, rich_catalog())
        with_rig = qa.step('drop_on_sheet', drop_workflow, qa, True)
        capture(qa, '01-workflow-on-sheet')
        # Drawer zoom: the same board as the Zen drawer shows it.
        qa.eval('''
win=drv.main_window()
area=next(a for a in win.screen.areas if a.type=='MIXIE')
area.type='VIEW_3D'
result=True
''')
        qa.click(surface='moodboard_drawer_grip')
        qa.wait('bpy.context.window_manager.mixar_moodboard_drawer_amount >= .99', timeout=5)
        qa.cmd('snap', path=str(OUT / '02-workflow-drawer-zoom.png'), area='VIEW_3D')
        qa.eval('''
win=drv.main_window()
area=next(a for a in win.screen.areas if a.type=='VIEW_3D')
area.type='MIXIE'
result=True
''')
        qa.step('one_undo', undo_once, qa)
        fixture(qa, rich_catalog(rig=False))
        without_rig = qa.step('drop_without_rig', drop_workflow, qa, False)
        capture(qa, '03-workflow-without-rig')
        qa.step('undo_without_rig', undo_once, qa)
        capture(qa, '04-board-after-undo')
        fixture(qa, rich_catalog(max_refs=False))
        menu = qa.step('menu_without_reference_limit', menu_hides_workflow, qa)
        result = {'credits': 0, 'screenshots': str(OUT), 'menu': menu,
                  'with_rig_links': len(with_rig['links']),
                  'without_rig_links': len(without_rig['links'])}
        (OUT / 'state-evidence.json').write_text(json.dumps(result, indent=2))
        return result
    finally:
        qa.eval('''
from mixar.bootstrap import generation_catalog_cache as catalog
with catalog._lock:
    catalog._catalog=bpy.app.driver_namespace.pop('_qa_sheet_catalog')
    catalog._bump_enum_version_locked()
catalog._on_catalog_swapped()
result=True
''')


if __name__ == '__main__':
    run_scenario('moodboard_character_sheet_workflow', run)
