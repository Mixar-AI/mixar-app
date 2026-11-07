# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Disposable background process for UV shader evaluation and web export."""

import json
from pathlib import Path
import sys

import bpy


def run(plan_path):
    folder = Path(plan_path).parent
    try:
        plan = json.loads(Path(plan_path).read_text())
        bpy.ops.wm.open_mainfile(filepath=str(folder / 'snapshot.blend'))
        scene = bpy.data.scenes[plan['scene']]
        bpy.context.window.scene = scene
        # Also supports replaying against source without changing an installed bundle.
        from mixar.modules.web_publish import core
        core.__path__.insert(0, str(Path(__file__).parent))
        from mixar.modules.web_publish.core.shader_textures import bake_shader_textures
        from mixar.modules.web_publish.core.glb_export import (
            export_glb, collect_scene_meta, collect_camera_config,
        )

        meshes = [scene.objects[name] for name in plan['meshes']]

        def progress(done, total):
            temporary = folder / 'progress.tmp'
            temporary.write_text(json.dumps({'done': done, 'total': total}))
            temporary.replace(folder / 'progress.json')

        meta = collect_scene_meta(scene, meshes)
        camera = collect_camera_config(scene)
        bake_shader_textures(meshes, plan['materials'], progress)
        result = export_glb(str(folder / 'scene.glb'), meshes, plan['animation'], scene)
        verified = result.get('verification', {})
        meta['textures'] = verified.get('images', meta['textures'])
        meta['triangles'] = verified.get('triangles', meta['triangles'])
        result['_publish_scene_meta'] = meta
        result['_publish_camera_config'] = camera
        (folder / 'result.json').write_text(json.dumps({'ok': True, 'result': result}))
    except Exception:
        import traceback
        traceback.print_exc()
        # Keep local paths and shader contents in the local worker log only.
        (folder / 'result.json').write_text(json.dumps({'ok': False}))
        raise


if __name__ == '__main__':
    run(sys.argv[sys.argv.index('--') + 1])
