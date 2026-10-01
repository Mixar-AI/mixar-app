#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real-app permission/import checks plus native registry-save failure/retry.

No agent credits. Requires QA_HARNESS, MIXAR_QA_PORT, QA_FOLDER_FIXTURES and
QA_SCENARIO_OUT. Use disposable fixtures and an isolated QA app.
"""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA
from context_folder_checklist_e2e import clear, pick, dismiss_reports
from generation_reference_column_e2e import capture, pause


def run():
    qa = QA()
    out = Path(os.environ['QA_SCENARIO_OUT'])
    root = Path(os.environ['QA_FOLDER_FIXTURES'])
    script = Path(__file__).with_name('context_folder_extra_checks.py').resolve()
    rows = qa.eval(
        "import importlib.util\n"
        f"spec=importlib.util.spec_from_file_location('folder_extra',{str(script)!r})\n"
        "m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)\n"
        f"result=m.run({str(root)!r},drv.main_window().scene)")
    clear(qa)
    candidate = root / '12-Registry-Failure'
    candidate.mkdir(exist_ok=True)
    qa.eval(
        "from mixar.modules.context_folder.core.registry import get_registry\n"
        "r=get_registry()\n"
        "assert not hasattr(r,'_qa_original_save')\n"
        "r._qa_original_save=r._save\n"
        "def denied(): raise PermissionError('QA simulated settings write denial')\n"
        "r._save=denied\nresult=True")
    try:
        pick(qa, candidate)
        pause(qa, .5)
        qa.wait("any('Could not save' in h.get('text','') for h in drv.find(popup=True))",timeout=5)
        qa.eval(
            "from mixar.modules.context_folder.core.registry import get_registry\n"
            "r=get_registry()\n"
            "assert len(drv.main_window().scene.mixie_context_folders)==0\n"
            f"assert {str(candidate)!r} not in r._load().values()\nresult=True")
        capture(qa, out, 'registry-save-error')
        rows.append({'case': 'registry write denial adds no chip or mapping', 'status': 'PASS'})
    finally:
        qa.eval("from mixar.modules.context_folder.core.registry import get_registry\n"
                "r=get_registry();r._save=r._qa_original_save;del r._qa_original_save\nresult=True")
    dismiss_reports(qa)
    pick(qa, candidate)
    qa.eval("from mixar.modules.context_folder.core.registry import get_registry, FolderRegistry\n"
            "s=drv.main_window().scene\nassert len(s.mixie_context_folders)==1\n"
            f"assert str(FolderRegistry(get_registry().path).resolve(s.mixie_context_folders[0].folder_id))=={str(candidate)!r}\n"
            "result=True")
    rows.append({'case': 'native retry persists attachment across registry reload', 'status': 'PASS'})
    capture(qa, out, 'registry-save-retry')
    (out / 'failure-checks.json').write_text(json.dumps(rows, indent=2))
    print(json.dumps(rows, indent=2))
    assert all(r['status']=='PASS' for r in rows)


if __name__ == '__main__':
    run()
