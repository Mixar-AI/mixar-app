#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit regression: playing a clip must not change any object's visibility.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4899 \
QA_SCENARIO_OUT=/tmp/animation-visibility python3 tests/qa/animation_visibility_e2e.py

Reproduces an enclosing low-poly helper sphere hidden through collection or
view-layer visibility. Play only solos an NLA track and sets the preview
range, so the visibility seen while playing and after Stop must equal the
original. Setup uses eval; playback uses the real browser and toolbar UI.
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ensure_scenes_drawer, run_scenario
from animation_browser_e2e import (BASE, COUNTS, FIXTURE, OUT, freeze_at, nla, open_browser,
                                   play, snap)


HELPERS = BASE + """
s=w.scene
with bpy.context.temp_override(window=w,area=a,region=r):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2,radius=2.8,location=(0,0,1.1))
    sphere=bpy.context.object
    sphere.name='QA Helper object hidden'
    sphere.hide_set(True)
    for kind in ('collection disabled','collection hidden','excluded','nested hidden','multi linked'):
        col=bpy.data.collections.new('QA Helpers '+kind)
        s.collection.children.link(col)
        obj=sphere.copy()
        obj.name='QA Helper '+kind
        col.objects.link(obj)
        if kind=='multi linked':
            # A visible link wins even when another collection is hidden.
            s.collection.objects.link(obj)
            obj.scale=(.08,.08,.08)
            obj.location=(2.4,0,0)
            col.hide_viewport=True
        elif kind=='collection disabled':
            col.hide_viewport=True
        elif kind=='nested hidden':
            child=bpy.data.collections.new('QA Helpers nested child')
            col.children.link(child)
            child.objects.link(obj)
            col.objects.unlink(obj)
            col.hide_viewport=True
        else:
            layer=w.view_layer.layer_collection.children[col.name]
            if kind=='excluded': layer.exclude=True
            else: layer.hide_viewport=True
    for obj in w.view_layer.objects: obj.select_set(False)
    body=s.objects['QA Robot Body']
    body.select_set(True)
    w.view_layer.objects.active=body
    w.view_layer.update()
browser.invalidate()
result=True
"""

VISIBILITY = BASE + """
result={o.name:o.visible_get(view_layer=w.view_layer,viewport=a.spaces.active)
        for o in w.scene.objects}
"""


def run(qa):
    OUT.mkdir(parents=True,exist_ok=True)
    qa.cmd('wait_login',timeout=30)
    qa.cmd('reset_state')
    qa.dismiss_splash()
    qa.eval('exec(compile(open('+repr(str(FIXTURE))+ ").read(),'animation fixture','exec'))")
    qa.eval(HELPERS)
    ensure_scenes_drawer(qa)
    original=qa.eval(VISIBILITY)
    baseline=nla(qa)
    counts=qa.eval(COUNTS)
    assert original['QA Robot Body'] and original['QA Helper multi linked']
    assert not any(visible for name,visible in original.items()
                   if name.startswith('QA Helper ') and name!='QA Helper multi linked')
    snap(qa,'01-hidden-helpers-source')
    for clip in ('Wave','Walk'):
        open_browser(qa)
        play(qa,clip,clip+' stored')
        freeze_at(qa,25)
        qa.press('ESC')
        snap(qa,'02-'+clip.lower()+'-soloed')
        during=qa.eval(VISIBILITY)
        assert during==original, {'source':original,'playing':during}
        qa.click(op='MIXAR_OT_animation_stop',region_type='HEADER')
        assert qa.eval(VISIBILITY)==original
        stopped=nla(qa)
        assert stopped['tracks']==baseline['tracks'] and stopped['preview']==baseline['preview']
        assert qa.eval(COUNTS)==counts
    qa.step('collection_and_layer_visibility_preserved',lambda:True)
    snap(qa,'03-restored-source')
    return {'hidden_helpers':5,'clips':['Wave','Walk'],
            'source_unchanged':True,'evidence':str(OUT)}


if __name__=='__main__':
    run_scenario('animation_visibility_e2e',run)
