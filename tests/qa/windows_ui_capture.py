# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Add process-scoped Windows compositor evidence to existing free replays.

QA_UI_CASE selects a reviewed replay. This wrapper does not change its checks;
it supplements each framebuffer capture with the visible native desktop.
"""
import importlib
import json
import os
from pathlib import Path
import sys
import traceback

HARNESS = Path(os.environ['QA_HARNESS'])
sys.path[:0] = [str(HARNESS), str(HARNESS / 'scenarios')]
from lib import QA, run_scenario
from windows_transcript_opacity_e2e import desktop_capture

ALLOWED = {
    'island_all_tabs_e2e', 'island_tab_alignment_e2e', 'island_media_tabs_e2e',
    'moodboard_drawer_tools_e2e', 'moodboard_parameter_help_e2e',
    'moodboard_node_dropdowns_e2e', 'ui_draft_interactions_e2e',
    'windows_workflow_ui_e2e', 'windows_direct_open_e2e',
    'windows_moodboard_hit_zones_e2e',
}


def install_captures(qa, folder):
    identity = qa.eval("import os,keyring\n"
        "from mixar.modules.common.utils import credential_store as store\n"
        "assert os.environ.get('MIXAR_QA')=='1'\n"
        "assert type(keyring.get_keyring()).__name__=='QAMemoryKeyring'\n"
        "assert store.set_secret.__module__=='qa_boot'\n"
        "result={'pid':os.getpid()}")
    original = QA.cmd
    rows = []

    def native(label):
        destination = folder / 'native' / f'{len(rows):03d}-{Path(label).stem}'
        snapshot = desktop_capture(identity['pid'], destination)
        rows.append({'label': label, 'snapshot': snapshot})
        (folder / 'native-captures.json').write_text(json.dumps(rows, indent=2))

    def command(self, cmd, _sock_timeout=None, **kwargs):
        result = original(self, cmd, _sock_timeout=_sock_timeout, **kwargs)
        if cmd == 'snap':
            native(kwargs.get('path', 'screenshot'))
        return result

    QA.cmd = command
    # This helper captures GPU region buffers directly, without QA.cmd('snap').
    helper = importlib.import_module('chat_refine_lifecycle_e2e')
    def capture(client, output, name):
        # The region-texture helper is needed for macOS glass. Windows has a
        # working whole-window buffer and independently captured compositor.
        header = {'area_type': 'AGENT_BUBBLE', 'region_type': 'HEADER',
                  'op': 'WM_OT_context_set_enum', 'text': 'Agent chat'}
        client.wait(f'bool(drv.find(**{header!r}))', timeout=10)
        path = str(output / (name + '.png'))
        client.cmd('snap', path=path, target=header, margin=3000)
        return path

    helper.capture = capture
    return native


def run(qa):
    assert sys.platform == 'win32', 'Windows compositor wrapper requires Windows'
    name = os.environ['QA_UI_CASE']
    assert name in ALLOWED, f'Unreviewed UI replay: {name}'
    folder = Path(os.environ['QA_SCENARIO_OUT'])
    folder.mkdir(parents=True, exist_ok=True)
    native = install_captures(qa, folder)
    module = importlib.import_module(name)
    try:
        if name.startswith('moodboard_'):
            from windows_moodboard_navigation import adapt
            adapt(module, qa, folder)
        if name in {'island_tab_alignment_e2e', 'island_media_tabs_e2e'}:
            # These older layout replays invoke the low-level show operator.
            # Establish the real user open path first; direct-show behavior is
            # covered separately by windows_direct_open_e2e. Earlier direct-
            # show/F3 diagnostic failures remain in their own evidence folders.
            qa.open_chat()
        if name == 'moodboard_parameter_help_e2e':
            # Guest startup has no member catalog. Metadata is an explicit
            # UI-only fixture; queue submission is refused and state restored.
            from catalog_fixture import with_catalog_fixture
            result = with_catalog_fixture(module.run)(qa)
        else:
            result = module.run(qa)
        native('completed')
        return {'replay': name, 'result': result, 'native_evidence': True}
    except Exception:
        (folder / 'traceback.txt').write_text(traceback.format_exc())
        try:
            (folder / 'failure-widgets.json').write_text(json.dumps(qa.find(limit=5000), indent=2))
            (folder / 'failure-island.json').write_text(json.dumps(qa.island_state(), indent=2))
        except Exception as diagnostic_error:
            (folder / 'diagnostic-error.txt').write_text(repr(diagnostic_error))
        native('failure-before-cleanup')
        raise


if __name__ == '__main__':
    run_scenario('windows_ui_capture', run)
