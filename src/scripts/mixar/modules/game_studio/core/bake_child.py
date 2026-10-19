# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Entry script of the background bake process (``bake_job`` starts it):

    <Mixar> -b <temp copy> --python bake_child.py -- --mixar-bake <config.json>
                                                     --mixar-result <result.json>

The process opens the temporary copy the user's session saved, bakes its
materials (``bake_run``) and writes the whole game package with the usual
``exporter.write_package``. Progress goes out as ``MIXAR_PROGRESS {json}``
lines on stdout, the protocol ``godot_runner.run`` already reads.

The lane runs from the SAME TREE as this script (the package's directories
are put first on the imported Mixar packages' paths), so a parent running a
source tree never pairs with an installed bundle's older exporter. The
result names the files it loaded.
"""

import json
import os
import sys
import time
import traceback

RESULT_SCHEMA = "mixar_bake_result_v1"


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    values = {}
    for flag in ("--mixar-bake", "--mixar-result"):
        if flag in argv:
            values[flag] = argv[argv.index(flag) + 1]
    return values


def _use_own_tree():
    """Make the game_studio and space_mixie_chat packages resolve from this
    script's tree first, dropping copies already imported from elsewhere."""
    import importlib
    modules = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for package, rel in (("mixar.modules.space_mixie_chat", "space_mixie_chat"),
                         ("mixar.modules.space_mixie_chat.core", "space_mixie_chat/core"),
                         ("mixar.modules.game_studio", "game_studio"),
                         ("mixar.modules.game_studio.core", "game_studio/core")):
        module = importlib.import_module(package)
        path = os.path.join(modules, rel)
        if path not in module.__path__:
            module.__path__.insert(0, path)
    for name in list(sys.modules):
        if (name.startswith("mixar.modules.space_mixie_chat.core.") and "export" in name) or \
                name.startswith("mixar.modules.game_studio.core."):
            del sys.modules[name]
    return modules


def _apply_dirty_images(manifest_path):
    """Put the session's painted-but-unsaved pixels into this copy and repack
    them, so both the bake and the glTF exporter read the live pixels."""
    if not manifest_path or not os.path.isfile(manifest_path):
        return
    import bpy
    import numpy as np
    with open(manifest_path, encoding="utf-8") as handle:
        for item in json.load(handle):
            image = bpy.data.images.get(item["name"])
            if image is None or tuple(image.size) != (item["width"], item["height"]):
                continue
            pixels = np.load(item["pixels"])
            if len(pixels) != len(image.pixels):
                continue
            image.pixels.foreach_set(pixels)
            image.update()
            image.pack()


def _single_user_object_relative(scene):
    """Instances whose material reads Object Info / object coordinates each
    get their own mesh copy, so each bakes its own variation."""
    from mixar.modules.game_studio.core import bake_plan
    for obj in scene.objects:
        data = getattr(obj, "data", None)
        if obj.type == 'MESH' and data is not None and data.users > 1 and any(
                bake_plan.material_verdict(m)["per_object"] for m in bake_plan._materials(obj)):
            obj.data = data.copy()


def progress(pct, message, step="bake"):
    print("MIXAR_PROGRESS " + json.dumps({"step": step, "pct": round(float(pct), 1), "message": message}),
          flush=True)


def _write(path, result):
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(dict(result, schema=RESULT_SCHEMA), handle, default=str)
    os.replace(temp, path)


def main():
    args = _args()
    result_path = args.get("--mixar-result")
    started = time.monotonic()
    result = {"ok": False, "action": "bake", "error": None, "error_code": None}
    try:
        with open(args["--mixar-bake"], encoding="utf-8") as handle:
            config = json.load(handle)
        tree = _use_own_tree()
        import bpy
        from mixar.modules.game_studio.core import bake_run, exporter, roles, visuals
        from mixar.modules.space_mixie_chat.core import export_emission
        result["loaded"] = {"tree": tree, "exporter": exporter.__file__,
                            "export_emission": export_emission.__file__}
        scene = bpy.data.scenes.get(config.get("scene") or "") or bpy.context.scene
        if bpy.context.window is not None and bpy.context.window.scene is not scene:
            bpy.context.window.scene = scene
        progress(2, "Preparing the bake")
        _apply_dirty_images(config.get("dirty_images"))
        _single_user_object_relative(scene)
        objects, _excluded = visuals.split_visible([o for o in roles.game_objects(scene) if roles.in_game(o)])
        bake_started = time.monotonic()
        stats = bake_run.bake_scene(scene, objects, config["cache_dir"],
                                    lambda pct, message: progress(5 + 0.85 * pct, message))
        stats["seconds"] = round(time.monotonic() - bake_started, 2)
        progress(92, "Exporting the baked scene")
        package = exporter.write_package(scene, game_dir=config["game_dir"])
        result.update(ok=bool(package["ok"]), bake=stats, package={
            key: package.get(key) for key in ("ok", "errors", "warnings", "game_dir", "export_dir", "export",
                                              "combat_proof")})
        if not package["ok"]:
            result.update(error="; ".join(package["errors"]) or "export failed", error_code="export_failed")
        progress(100, "Baked and exported")
    except Exception as exc:  # noqa: BLE001 — reported to the parent job
        result.update(error=f"{exc.__class__.__name__}: {exc}", error_code="bake_failed",
                      traceback=traceback.format_exc()[-4000:])
    result["duration_s"] = round(time.monotonic() - started, 2)
    if result_path:
        _write(result_path, result)
    sys.stdout.flush()
    os._exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
