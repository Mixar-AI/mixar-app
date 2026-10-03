# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Read-only replay of repeated scoped lookups in the generated forest fixture.

Open the saved forest scene from modeling_prompt_e2e first. The defaults match
the recorded 525-instance fixture; other generations may need different names.
The original check reproduces the access pattern that caused the measured pause.
No generation request or additional Blender process is started.
"""
import argparse
import json
from pathlib import Path
import sys


def main():
    repo = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=4791)
    parser.add_argument('--harness', type=Path, default=repo.parent / 'mixar-qa-harness')
    parser.add_argument('--scope-template', type=Path, default=repo.parent /
                        'mixar-backend/modules/agent/tools/scripts/workspace/data_view.py')
    parser.add_argument('--root', default='forest_scatter_Forest')
    parser.add_argument('--source-prefix', default='forest_sources_Forest_Source_')
    parser.add_argument('--out', type=Path, default=Path('/tmp/forest-scoped-lookups.json'))
    args = parser.parse_args()
    sys.path.insert(0, str(args.harness / 'scenarios'))
    from lib import QA
    qa = QA(port=args.port)
    assert qa.status()['state'] == 'IDLE'
    assert qa.eval("import os; result=os.environ.get('MIXAR_QA')=='1'")
    session = qa.eval('result=drv.main_window().scene.mixie_session_id')
    prefix = '__PARAMS__=' + repr({'workspace_session': session}) + '\n'
    prefix += args.scope_template.read_text() + '\n'
    setup = f"obs=list(__ws_data.objects[{args.root!r}].children)\nassert len(obs)>0\n"
    original = setup + (
        "print('ALL LINKED', all(o.data is __ws_data.objects["
        + repr(args.source_prefix) + "+o.name.split('_')[2]].data for o in obs))\n"
    )
    cached = setup + (
        "kinds=set(o.name.split('_')[2] for o in obs)\n"
        "sources={k:__ws_data.objects[" + repr(args.source_prefix) + "+k].data for k in kinds}\n"
        "print('ALL LINKED', all(o.data is sources[o.name.split('_')[2]] for o in obs))\n"
    )
    scripts = {'original': prefix + original, 'cached_sources': prefix + cached}
    results = qa.cmd('eval', code='scripts=' + repr(scripts) + '\n' + """
import time
from mixar.modules.space_mixie_chat.core.executor import ScriptExecutor
w=drv.main_window()
result={}
with bpy.context.temp_override(window=w):
    for name,script in scripts.items():
        start=time.perf_counter()
        receipt=ScriptExecutor().execute(script,push_undo=False,session_id=w.scene.mixie_session_id)
        result[name]={'seconds':time.perf_counter()-start,'success':receipt.success,
                      'output':receipt.output,'error':receipt.error}
""", _sock_timeout=60)
    args.out.write_text(json.dumps(results, indent=2))
    assert all(r['success'] and 'ALL LINKED True' in r['output'] for r in results.values()), results
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
