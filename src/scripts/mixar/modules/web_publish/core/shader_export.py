# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Asynchronous shader-export worker; bpy stays on the host's main thread."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

import bpy

from mixar.modules.common.i18n import n_


def start(folder, scene, meshes, plans, animation, state, finished):
    """Snapshot without saving/changing the user's file; return immediately.

    Process launch, polling and result-file reads run on a worker thread.
    The completion callback alone is handed back through a Blender timer.
    """
    root = Path(folder)
    # Blender ID serialization must run on its owning thread. Only this
    # immutable snapshot crosses to the worker; the artist can keep editing.
    saved_source = bpy.data.filepath if not bpy.data.is_dirty else ''
    if saved_source and any(path.startswith('//') for path in bpy.utils.blend_paths(packed=False)):
        saved_source = ''  # Relative dependencies need Blender's path remapping.
    if not saved_source:
        bpy.data.libraries.write(str(root / 'snapshot.blend'), {scene},
                                 path_remap='ABSOLUTE', compress=False)
    plan_path = root / 'shader-plan.json'
    plan_path.write_text(json.dumps({'scene': scene.name,
                                    'meshes': [obj.name for obj in meshes],
                                    'materials': plans, 'animation': animation}))
    binary = bpy.app.binary_path
    script = str(Path(__file__).with_name('shader_export_worker.py'))
    outcome = {}
    owner = state.publish_id

    def work():
        process = None
        try:
            if state.cancel_requested or state.publish_id != owner:
                outcome['cancelled'] = True
                return
            if saved_source:
                shutil.copyfile(saved_source, root / 'snapshot.blend')
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            with (root / 'shader-worker.log').open('w') as log:
                process = subprocess.Popen(
                    [binary, '-b', '--factory-startup', '--disable-autoexec',
                     '--python', script, '--', str(plan_path)],
                    stdout=log, stderr=subprocess.STDOUT, creationflags=flags,
                    env={**os.environ, 'MIXAR_SHADER_EXPORT_WORKER': '1'})
                started = time.monotonic()
                while process.poll() is None:
                    if state.cancel_requested or state.publish_id != owner or time.monotonic() - started > 1800:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
                        outcome['cancelled'] = state.cancel_requested or state.publish_id != owner
                        if not outcome['cancelled']:
                            outcome['error'] = n_('Shader texture preparation timed out')
                        return
                    try:
                        progress = json.loads((root / 'progress.json').read_text())
                        done, total = progress['done'], max(1, progress['total'])
                        state.set_status('EXPORTING', n_('Preparing shader textures ({done}/{total})…'),
                                         0.02 + 0.6 * done / total, done=done, total=total)
                    except (OSError, ValueError, KeyError):
                        pass
                    time.sleep(0.25)
            if process.returncode:
                raise RuntimeError('shader worker failed')
            result = json.loads((root / 'result.json').read_text())
            if not result.get('ok'):
                raise RuntimeError('shader worker failed')
            outcome['result'] = result['result']
        except Exception:
            outcome['error'] = n_('Could not prepare shader textures; publication stopped')
        finally:
            outcome['ready'] = True

    def poll():
        if not outcome.get('ready'):
            return 0.25
        finished(outcome)
        return None

    threading.Thread(target=work, name='MixarShaderExport', daemon=True).start()
    bpy.app.timers.register(poll, first_interval=0.25, persistent=True)
