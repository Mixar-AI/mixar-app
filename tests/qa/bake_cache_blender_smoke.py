# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Headless proof that an export the bake budget cut short continues on the
next export, against REAL Cycles bakes in Blender 5.2.

Run inside the built app, no backend and no credits::

    <Mixar.app>/Contents/MacOS/Mixar -b --python tests/qa/bake_cache_blender_smoke.py

Six blocks, each with its own procedural material. The budget is made to run
out after two bakes. Export 1 bakes two and skips four with an "export again"
warning; export 2 reuses those two and bakes two more; export 3 finishes. A
fresh export with an empty cache and no budget must embed byte-identical
textures (the reused pixels line up with the export's own UVs), and editing
one material bakes that one again while the rest are reused. The Oct 27
cs-go-2 town skipped four materials on every retry: each export started over.

The ``src/`` modules are loaded over the bundle's copies by file. Prints one
``__RESULT__`` JSON line.
"""

import hashlib
import importlib.util
import json
import os
import shutil
import struct
import sys
import tempfile
import traceback

import bpy

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC = os.path.join(ROOT, "src", "scripts")
CORE = "mixar.modules.space_mixie_chat.core"
SRC_MODULES = tuple(f"{CORE}.{m}" for m in (
    "export_verification_status", "export_gltf_bounds", "export_verify", "export_clips",
    "export_materials", "export_bake_cache", "export_bake", "engine_targets", "export_package",
))


def _load_src(dotted):
    path = os.path.join(SRC, *dotted.split(".")) + ".py"
    spec = importlib.util.spec_from_file_location(dotted, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[dotted] = module
    spec.loader.exec_module(module)
    return module


def _images(path):
    """sha256 of every embedded image, in file order."""
    with open(path, "rb") as handle:
        data = handle.read()
    size = struct.unpack("<I", data[12:16])[0]
    doc = json.loads(data[20:20 + size])
    binary = data[20 + size + 8:]
    out = []
    for image in doc.get("images", []):
        view = doc["bufferViews"][image["bufferView"]]
        start = view.get("byteOffset", 0)
        out.append([image.get("name"), hashlib.sha256(binary[start:start + view["byteLength"]]).hexdigest()])
    return sorted(out)


def _scene():
    bpy.ops.wm.read_homefile(use_empty=True)
    names = []
    for i in range(6):
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(i * 1.5, 0, 0.5))
        obj = bpy.context.object
        obj.name = f"Block_{i}"
        mat = bpy.data.materials.new(f"Plaster_{i}")
        mat.use_nodes = True
        tree = mat.node_tree
        noise = tree.nodes.new("ShaderNodeTexNoise")
        noise.name = "Noise"
        noise.inputs["Scale"].default_value = 3.0 + i
        bsdf = tree.nodes["Principled BSDF"]
        tree.links.new(noise.outputs["Color"], bsdf.inputs["Base Color"])
        tree.links.new(noise.outputs["Fac"], bsdf.inputs["Roughness"])
        obj.data.materials.append(mat)
        names.append(obj.name)
    return names


def main():
    cache = tempfile.mkdtemp(prefix="mixar_bake_cache_")
    os.environ["MIXAR_AGENT_CACHE_DIR"] = cache
    sys.path.insert(0, SRC)
    for dotted in SRC_MODULES:
        _load_src(dotted)
    package = sys.modules[f"{CORE}.export_package"]
    bake = sys.modules[f"{CORE}.export_bake"]
    real_clock, real_bake = bake.time.perf_counter, bake._bake_channels
    state = {"bakes": 0, "limit": None}

    def counted(*args, **kwargs):
        state["bakes"] += 1
        return real_bake(*args, **kwargs)

    class Clock:  # the budget "runs out" once ``limit`` bakes ran this export
        @staticmethod
        def perf_counter():
            over = state["limit"] is not None and state["bakes"] >= state["limit"]
            return real_clock() + (1e6 if over else 0.0)

    bake._bake_channels = counted
    bake.time = Clock
    names = _scene()

    def export(tag, limit):
        state["bakes"], state["limit"] = 0, limit
        res = package.export_package(names, fmt="glb", filename=f"bake_smoke_{tag}")
        root = package.destination("mixar_exports", f"bake_smoke_{tag}", create=False)
        images = _images(os.path.join(root, f"bake_smoke_{tag}.glb"))
        shutil.rmtree(root, ignore_errors=True)
        report = res["baked_materials"] or {}
        return {"fresh": sorted(b["material"] for b in report.get("baked", []) if not b["reused"]),
                "reused": sorted(b["material"] for b in report.get("baked", []) if b["reused"]),
                "skipped": sorted(s["material"] for s in report.get("skipped", [])),
                "warning": res["warning"], "bakes": state["bakes"], "images": images}

    first, second, third = export("1", 2), export("2", 2), export("3", 2)
    shutil.rmtree(cache, ignore_errors=True)
    os.makedirs(cache)
    clean = export("clean", None)
    bpy.data.materials["Plaster_3"].node_tree.nodes["Noise"].inputs["Scale"].default_value = 11.0
    edited = export("edited", None)
    shutil.rmtree(cache, ignore_errors=True)
    checks = {
        "first_partial": len(first["fresh"]) == 2 and len(first["skipped"]) == 4 and not first["reused"],
        "first_warns": "export again" in first["warning"],
        "second_continues": (second["reused"] == first["fresh"] and len(second["fresh"]) == 2
                             and len(second["skipped"]) == 2),
        "third_finishes": len(third["reused"]) == 4 and len(third["fresh"]) == 2 and not third["skipped"]
                          and "export again" not in third["warning"],
        "reused_pixels_identical": third["images"] == clean["images"] and len(clean["images"]) == 12,
        "edit_rebakes_only_it": edited["fresh"] == ["Plaster_3"] and len(edited["reused"]) == 5,
        "edit_changes_its_pixels": edited["images"] != clean["images"],
    }
    clean_by_name = dict(map(tuple, clean["images"]))
    mismatched = sorted(n for n, h in third["images"] if clean_by_name.get(n) != h)
    return {"ok": all(checks.values()), "checks": checks, "mismatched_images": mismatched,
            "image_names": [n for n, _ in third["images"]],
            "runs": {k: {x: v for x, v in r.items() if x != "images"}
                     for k, r in (("1", first), ("2", second), ("3", third), ("clean", clean),
                                  ("edited", edited))}}


if __name__ == "__main__":
    try:
        out = main()
    except Exception:
        out = {"ok": False, "error": traceback.format_exc()}
    print("__RESULT__ " + json.dumps(out))
    sys.stdout.flush()
