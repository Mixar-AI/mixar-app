# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Entry script of the background process that cleans a remix source:

    <Mixar> -Y -b <copy.mixar> --python source_child.py -- --mixar-result <result.json>

It removes the creator's agent conversation, session ids and store
identity from every datablock (``lineage.scrub_file``), packs external
files and drops absolute paths, checks nothing private is left, and saves
the copy in place, compressed. The lineage stamp is kept: a remix of a remix still names its
parent.
"""

import json
import os
import sys
import traceback

RESULT_SCHEMA = "mixar_remix_source_result_v1"


def _neutralise_paths(bpy) -> dict:
    """Pack what the project reads from the creator's disk, then drop the
    absolute paths. A remixer has none of those files, and the paths name the
    creator's account and folders. Best effort: a file that cannot be packed
    keeps working for nobody, but its path is still removed."""
    done = {"packed": 0, "images": 0, "texts": 0, "render": 0, "libraries": len(bpy.data.libraries)}
    try:
        bpy.ops.file.pack_all()
        done["packed"] = 1
    except Exception:  # noqa: BLE001
        pass
    for image in bpy.data.images:
        path = image.filepath or ""
        if path and not path.startswith("//"):
            image.filepath = "//" + os.path.basename(path.replace("\\", "/"))
            done["images"] += 1
    for text in bpy.data.texts:
        if text.filepath:
            text.filepath = ""
            done["texts"] += 1
    for scene in bpy.data.scenes:
        if scene.render.filepath and not scene.render.filepath.startswith("//"):
            scene.render.filepath = "//"
            done["render"] += 1
    return done


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    result_path = argv[argv.index("--mixar-result") + 1] if "--mixar-result" in argv else ""
    result = {"schema": RESULT_SCHEMA, "ok": False, "action": "remix_source", "error": None,
              "error_code": None}
    try:
        import bpy
        from mixar.modules.remix.core import lineage
        if not lineage.has_system_props(bpy.context.scene):
            # Without this API the stored conversation cannot be seen or removed.
            raise RuntimeError("this Mixar cannot read stored properties; refusing to make a source")
        cleared = lineage.scrub_file(bpy.data)
        paths = _neutralise_paths(bpy)
        # Never hand back a file that still holds something private: the parent
        # uploads the copy only when this process reports ok.
        left = lineage.leftovers(bpy.data)
        if left:
            raise RuntimeError(f"private data could not be removed: {dict(list(left.items())[:5])}")
        bpy.ops.wm.save_mainfile(compress=True)
        result.update(ok=True, cleared=cleared, paths=paths, size_bytes=os.path.getsize(bpy.data.filepath))
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
