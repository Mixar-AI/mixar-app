# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Entry script of the background process that cleans a remix source:

    <Mixar> -Y -b <copy.mixar> --python source_child.py -- --mixar-result <result.json>

It removes the creator's agent conversation, session ids and store
identity from every scene (``lineage.scrub``) and saves the copy in place,
compressed. The lineage stamp is kept: a remix of a remix still names its
parent.
"""

import json
import os
import sys
import traceback

RESULT_SCHEMA = "mixar_remix_source_result_v1"


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    result_path = argv[argv.index("--mixar-result") + 1] if "--mixar-result" in argv else ""
    result = {"schema": RESULT_SCHEMA, "ok": False, "action": "remix_source", "error": None,
              "error_code": None}
    try:
        import bpy
        from mixar.modules.remix.core import lineage
        cleared = {scene.name: lineage.scrub(scene) for scene in bpy.data.scenes}
        # Objects, materials and the rest can carry the same kind of stored value.
        others = 0
        for collection in (bpy.data.objects, bpy.data.materials, bpy.data.meshes, bpy.data.images,
                           bpy.data.collections, bpy.data.worlds, bpy.data.cameras, bpy.data.lights,
                           bpy.data.node_groups, bpy.data.actions, bpy.data.armatures):
            for idblock in collection:
                others += len(lineage.scrub_stored(idblock))
        # Never hand back a file that still holds something private: the parent
        # uploads the copy only when this process reports ok.
        left = {scene.name: lineage.private_keys(scene) for scene in bpy.data.scenes}
        left = {name: keys for name, keys in left.items() if keys}
        if left:
            raise RuntimeError(f"private data could not be removed: {left}")
        bpy.ops.wm.save_mainfile(compress=True)
        result.update(ok=True, cleared=cleared, cleared_elsewhere=others,
                      size_bytes=os.path.getsize(bpy.data.filepath))
    except Exception as exc:  # noqa: BLE001 — reported to the parent job
        result.update(error=f"{exc.__class__.__name__}: {exc}", error_code="source_failed",
                      traceback=traceback.format_exc()[-4000:])
    if result_path:
        temp = result_path + ".tmp"
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(result, handle, default=str)
        os.replace(temp, result_path)
    sys.stdout.flush()
    os._exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
