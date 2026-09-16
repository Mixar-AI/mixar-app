# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Replayable real-app catalog -> UI search -> scatter -> save/reopen scenario.

Run against a dedicated QA profile (resets its scene):
  QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4782 python3 tests/qa/asset_library_e2e.py
Uses synthetic .blend assets. No training or generation request is made by this scenario.
"""
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
OUT = Path(os.environ.get('ASSET_QA_OUT', '/tmp/mixar-assets-qa'))


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    imports = f'import sys, importlib; sys.path.insert(0, {str(ROOT)!r}); '
    qa.step('Author synthetic biome library', qa.eval, imports+
        f'import asset_library_fixture as fixture; importlib.reload(fixture); result=fixture.setup({str(OUT / "biomes")!r})')
    # Layout setup is fixture work; search and placement below use semantic clicks.
    if not qa.eval('result=any(a.type=="FILE_BROWSER" for a in bpy.context.screen.areas)'):
        qa.eval('area=next(a for a in bpy.context.screen.areas if a.type=="VIEW_3D")\n'
                'with bpy.context.temp_override(area=area):\n'
                '    bpy.ops.screen.area_split(direction="VERTICAL",factor=.58)\nresult=True')
        qa.eval('area=max(bpy.context.screen.areas,key=lambda a:a.x)\n'
                'area.type="FILE_BROWSER"\narea.spaces.active.browse_mode="ASSETS"\n'
                'area.spaces.active.show_region_toolbar=True\nresult=True')
    qa.step('Refresh through UI', qa.click, op='MIXIE_OT_catalog_refresh')
    qa.wait('__import__("asset_library_fixture").catalog_ready()', timeout=60)
    qa.wait('not bpy.context.scene.mixie_asset_training.is_searching', timeout=60)
    qa.step('Search through UI', qa.click, op='MIXIE_OT_catalog_search')
    qa.wait('not bpy.context.scene.mixie_asset_training.is_searching', timeout=45)
    qa.step('Assert exact search results', qa.eval,
        'rows=bpy.context.scene.mixie_asset_training.search_results\n'
        'assert len(rows)==2 and len({r.asset_id for r in rows})==2\n'
        'assert all(r.revision and r.asset_type=="Collection" and r.available for r in rows)\nresult=True')
    qa.step('Scatter through UI', qa.click, op='MIXIE_OT_catalog_place', text='Scatter')
    qa.wait('any(c.get("mixar_scatter_slot") for c in bpy.context.scene.collection.children)', timeout=15)
    qa.cmd('snap', path=str(OUT / 'search-and-scatter.png'))
    qa.cmd('snap', path=str(OUT / 'search-panel.png'), target={'panel': 'MIXIE_PT_asset_library_search'})
    verdict = qa.step('Scope, replacement and rollback', qa.eval,
                      imports+'import asset_library_assertions as checks; importlib.reload(checks); result=checks.exercise()')
    qa.cmd('snap', path=str(OUT / 'two-terrain-scatter.png'), area='VIEW_3D')
    saved = str(OUT / 'library-scatter.blend')
    qa.step('Save', qa.eval, f'bpy.ops.wm.save_as_mainfile(filepath={saved!r}); result=True')
    qa.step('Reopen', qa.eval, f'bpy.ops.wm.open_mainfile(filepath={saved!r}); result=True')
    qa.wait('"Terrain B" in bpy.context.scene.objects', timeout=15)
    persistence = qa.step('Verify evaluated instances after reopen', qa.eval,
                         imports+'import asset_library_assertions as checks; result=checks.persisted()')
    qa.cmd('snap', path=str(OUT / 'reopened-scatter.png'), area='VIEW_3D')
    report = {'success': True, 'checks': verdict['checks']+['save_reopen'],
              'persistence': persistence, 'steps': qa.log}
    (OUT / 'report.json').write_text(json.dumps(report, indent=2))
    return report


if __name__ == '__main__':
    sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
    from lib import QA
    print(json.dumps(run(QA()), indent=2))
