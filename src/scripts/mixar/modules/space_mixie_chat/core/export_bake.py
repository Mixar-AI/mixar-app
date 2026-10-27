# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bake procedural materials to images on an export package's copies.

The glTF / FBX / USD exporters read a Principled BSDF whose inputs are image
textures or plain values. Anything else in front of an input (noise, brick,
colour ramps, mixes, bumps, an unbaked Mixar paint stack) is dropped, so the
asset arrives flat or blank in a game engine. ``baked_procedural_materials``
finds those materials on the package's COPIES, unwraps their faces into a
fresh UV layout (one texture set per material, shared by every copy that uses
it), bakes each linked channel with Cycles and points the copies at a plain
Principled/image material for the export. The user's objects, materials and
render settings are left as they were; the baked images and temporary
materials are freed on exit. Baked textures are kept between exports
(``export_bake_cache``): an unchanged material is reused before anything is
baked, so an export the time budget cut short continues on the next one.

Runs after ``export_materials`` swapped baked Mixar stacks, so a baked stack
is already image-based here and is not baked again.
"""

import math
import time
from contextlib import contextmanager

import bpy

from . import export_bake_cache as bake_cache

BAKE_UV = "MixarBake"
MAX_UV_LAYERS = 8
# (Principled input, file suffix, colour data)
CHANNELS = (
    ("Base Color", "basecolor", True),
    ("Metallic", "metallic", False),
    ("Roughness", "roughness", False),
    ("Alpha", "alpha", False),
    ("Emission Color", "emission", True),
    ("Normal", "normal", False),
)
_SRGB = {name: srgb for name, _, srgb in CHANNELS}
_SUFFIX = {name: suffix for name, suffix, _ in CHANNELS}
# Nodes the exporters read between an image and a Principled input.
_READABLE = {
    "ShaderNodeTexImage", "ShaderNodeMapping", "ShaderNodeTexCoord", "ShaderNodeUVMap",
    "ShaderNodeSeparateColor", "ShaderNodeSeparateRGB", "ShaderNodeNormalMap",
    "ShaderNodeVertexColor", "NodeReroute",
}
_COPIED_VALUES = ("Base Color", "Metallic", "Roughness", "Alpha", "Emission Color", "Emission Strength")


def _output(tree):
    for target in ("CYCLES", "ALL"):
        try:
            node = tree.get_output_node(target)
        except Exception:  # noqa: BLE001 - a stub tree, or an unknown target
            node = None
        if node is not None:
            return node
    return next((n for n in tree.nodes if getattr(n, "type", "") == "OUTPUT_MATERIAL"), None)


def _readable(socket):
    """True when everything feeding ``socket`` is something an exporter reads."""
    pending = [link.from_node for link in socket.links if not getattr(link, "is_muted", False)]
    seen = set()
    while pending:
        node = pending.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        if node.bl_idname not in _READABLE:
            return False
        for inp in node.inputs:
            pending.extend(link.from_node for link in inp.links if not getattr(link, "is_muted", False))
    return True


def plan(material):
    """What to bake for ``material``: None when an exporter reads it as is,
    else {"mode": "principled" | "surface", "channels": [Principled inputs]}.
    ``principled``: the surface is a Principled BSDF and at least one linked
    input is procedural; every linked input is baked through an emission.
    ``surface``: something other than a Principled BSDF drives the surface;
    its colour, roughness and normal passes are baked."""
    tree = getattr(material, "node_tree", None) if material is not None else None
    if tree is None:
        return None
    out = _output(tree)
    surface = out.inputs.get("Surface") if out is not None else None
    if surface is None or not surface.is_linked:
        return None
    node = surface.links[0].from_node
    if node.bl_idname == "ShaderNodeBsdfPrincipled":
        linked = [name for name, _, _ in CHANNELS
                  if node.inputs.get(name) is not None and node.inputs[name].is_linked]
        if all(_readable(node.inputs[name]) for name in linked):
            return None
        strength = node.inputs.get("Emission Strength")
        if ("Emission Color" in linked and strength is not None and not strength.is_linked
                and float(strength.default_value) == 0.0):
            linked.remove("Emission Color")
        return {"mode": "principled", "channels": linked}
    return {"mode": "surface", "channels": ["Base Color", "Roughness", "Normal"]}


def texture_size(area_m2, density=128, lo=256, hi=2048):
    """Square texture edge for a material covering ``area_m2`` of surface at
    ``density`` px per metre, a power of two in [lo, hi]."""
    px = math.sqrt(max(float(area_m2), 0.0)) * density
    edge = 2 ** math.ceil(math.log2(max(px, 1.0)))
    return int(min(hi, max(lo, edge)))


def _context(objs):
    ctx = {"active_object": objs[0], "object": objs[0], "selected_objects": list(objs),
           "selected_editable_objects": list(objs)}
    wm = bpy.context.window_manager
    if bpy.context.window is None and wm is not None and wm.windows:
        window = wm.windows[0]
        ctx.update(window=window, screen=window.screen)
    return ctx


def _select(objs):
    layer = bpy.context.view_layer
    for o in layer.objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    layer.objects.active = objs[0]


def _render_state(scene):
    bake = scene.render.bake
    return {
        "engine": scene.render.engine, "samples": scene.cycles.samples,
        "denoise": getattr(scene.cycles, "use_denoising", None),
        "margin": bake.margin, "margin_type": getattr(bake, "margin_type", None),
        "use_clear": bake.use_clear, "target": getattr(bake, "target", None),
        "normal_space": bake.normal_space, "selected_to_active": bake.use_selected_to_active,
    }


def _restore_render(scene, state):
    bake = scene.render.bake
    scene.render.engine = state["engine"]
    scene.cycles.samples = state["samples"]
    if state["denoise"] is not None:
        scene.cycles.use_denoising = state["denoise"]
    bake.margin = state["margin"]
    if state["margin_type"] is not None:
        bake.margin_type = state["margin_type"]
    bake.use_clear = state["use_clear"]
    if state["target"] is not None:
        bake.target = state["target"]
    bake.normal_space = state["normal_space"]
    bake.use_selected_to_active = state["selected_to_active"]


def _face_area(obj, indices):
    return sum(p.area for p in obj.data.polygons if p.material_index in indices)


def _add_bake_layers(objs):
    """A ``MixarBake`` layer per mesh, copied from its render UV map so faces
    that are not baked keep their UVs -> {obj: render map name or None}."""
    base = {}
    for o in objs:
        layers = o.data.uv_layers
        render = next((layer for layer in layers if layer.active_render), None)
        if render is not None:
            layers.active = render
        base[o] = render.name if render is not None else None
        layers.active = layers.new(name=BAKE_UV, do_init=True)
    return base


def _unwrap(objs, jobs):
    """Unwrap each material's faces, across every copy that uses it, into its
    own 0-1 square of ``MixarBake`` (one texture set per material)."""
    import bmesh

    _select(objs)
    with bpy.context.temp_override(**_context(objs)):
        bpy.ops.object.mode_set(mode="EDIT")
        try:
            for job in jobs:
                any_face = False
                for o in objs:
                    bm = bmesh.from_edit_mesh(o.data)
                    bm.select_mode = {"FACE"}
                    for v in bm.verts:
                        v.select = False
                    for e in bm.edges:
                        e.select = False
                    wanted = job["slots"].get(o, ())
                    for f in bm.faces:
                        f.select = False
                    for f in bm.faces:
                        if f.material_index in wanted:
                            f.select_set(True)
                            any_face = True
                    bmesh.update_edit_mesh(o.data, loop_triangles=False, destructive=False)
                if any_face:
                    bpy.ops.uv.smart_project(angle_limit=math.radians(66.0), island_margin=0.004,
                                             area_weight=0.0, correct_aspect=True, scale_to_bounds=False)
        finally:
            bpy.ops.object.mode_set(mode="OBJECT")


def _sink():
    """Faces of other materials on a baking copy render into this 1x1 image
    (Cycles refuses to bake a material with no active image)."""
    image = bpy.data.images.new("mixar_bake_sink", 1, 1)
    mat = bpy.data.materials.new("mixar_bake_sink")
    mat.use_nodes = True
    node = mat.node_tree.nodes.new("ShaderNodeTexImage")
    node.image = image
    mat.node_tree.nodes.active = node
    return mat, image


def _bake(objs, kind, margin, pass_filter=None):
    _select(objs)
    kwargs = dict(type=kind, margin=margin, use_clear=True, target="IMAGE_TEXTURES",
                  uv_layer=BAKE_UV, use_selected_to_active=False, normal_space="TANGENT")
    if pass_filter:
        kwargs["pass_filter"] = set(pass_filter)
    with bpy.context.temp_override(**_context(objs)):
        result = bpy.ops.object.bake(**kwargs)
    if "FINISHED" not in result:
        raise RuntimeError(f"{kind} bake returned {sorted(result)}")


def _bake_channels(job, size, margin, created_images):
    """Bake every channel of ``job`` into new images -> {input name: image}.
    The job's slots already hold its bake material (a copy of the original)."""
    p = job["plan"]
    mat = job["bake_material"]
    tree = mat.node_tree
    out = _output(tree)
    source = out.inputs["Surface"].links[0].from_node
    target = tree.nodes.new("ShaderNodeTexImage")
    tree.nodes.active = target
    objs = list(job["slots"])
    images = {}
    for name in p["channels"]:
        image = bpy.data.images.new(f"{job['material'].name}_{_SUFFIX[name]}", size, size,
                                    alpha=False, is_data=not _SRGB[name])
        created_images.append(image)
        image.generated_color = (0.5, 0.5, 1.0, 1.0) if name == "Normal" else (0.0, 0.0, 0.0, 1.0)
        target.image = image
        if name == "Normal":
            _bake(objs, "NORMAL", margin)
        elif p["mode"] == "surface":
            if name == "Base Color":
                _bake(objs, "DIFFUSE", margin, {"COLOR"})
            else:
                _bake(objs, "ROUGHNESS", margin)
        else:
            emission = tree.nodes.new("ShaderNodeEmission")
            emission.inputs["Strength"].default_value = 1.0
            tree.links.new(source.inputs[name].links[0].from_socket, emission.inputs["Color"])
            tree.links.new(emission.outputs[0], out.inputs["Surface"])
            try:
                _bake(objs, "EMIT", margin)
            finally:
                tree.links.new(source.outputs[0], out.inputs["Surface"])
                tree.nodes.remove(emission)
        images[name] = image
    return images


def _export_material(job, images):
    """A Principled/image material the exporters read: baked channels as
    textures on ``MixarBake``, every other input copied as a value."""
    src_mat = job["material"]
    mat = bpy.data.materials.new(f"{src_mat.name}_baked")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next((n for n in nt.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled"), None)
    if bsdf is None:
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        nt.links.new(bsdf.outputs[0], _output(nt).inputs["Surface"])
    if job["plan"]["mode"] == "principled":
        source = _output(src_mat.node_tree).inputs["Surface"].links[0].from_node
        for name in _COPIED_VALUES:
            src, dst = source.inputs.get(name), bsdf.inputs.get(name)
            if src is not None and dst is not None and not src.is_linked:
                try:
                    dst.default_value = src.default_value
                except (TypeError, ValueError):
                    pass
    for attr in ("surface_render_method", "blend_method"):
        if hasattr(src_mat, attr):
            try:
                setattr(mat, attr, getattr(src_mat, attr))
            except (TypeError, ValueError, AttributeError):
                pass
    uv = nt.nodes.new("ShaderNodeUVMap")
    uv.uv_map = BAKE_UV
    for name, image in images.items():
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = image
        nt.links.new(uv.outputs["UV"], tex.inputs["Vector"])
        if name == "Normal":
            normal = nt.nodes.new("ShaderNodeNormalMap")
            normal.uv_map = BAKE_UV
            nt.links.new(tex.outputs["Color"], normal.inputs["Color"])
            nt.links.new(normal.outputs["Normal"], bsdf.inputs["Normal"])
        elif _SRGB[name]:
            nt.links.new(tex.outputs["Color"], bsdf.inputs[name])
            if name == "Emission Color" and float(bsdf.inputs["Emission Strength"].default_value) == 0.0:
                bsdf.inputs["Emission Strength"].default_value = 1.0
        else:
            split = nt.nodes.new("ShaderNodeSeparateColor")
            nt.links.new(tex.outputs["Color"], split.inputs["Color"])
            nt.links.new(split.outputs[0], bsdf.inputs[name])
    return mat


def _finish_uvs(objs, base):
    """``MixarBake`` becomes each copy's only render map, under the old map's
    name, so materials that name it explicitly still find it."""
    for o in objs:
        layers = o.data.uv_layers
        bake = layers.get(BAKE_UV)
        if bake is None:
            continue
        name = base.get(o)
        if name and name != BAKE_UV and layers.get(name) is not None:
            layers.remove(layers[name])
            bake = layers.get(BAKE_UV)
            bake.name = name
        bake.active = True
        bake.active_render = True


def _relabel(images, name):
    """The baked images' UV map node and normal map keep pointing at the map
    under its final name."""
    for mat in images:
        for node in mat.node_tree.nodes:
            if node.bl_idname in ("ShaderNodeUVMap", "ShaderNodeNormalMap") and node.uv_map == BAKE_UV:
                node.uv_map = name


@contextmanager
def baked_procedural_materials(copies, *, density=128, max_px=2048, margin=8, budget_s=240.0):
    """Bake the procedural materials on ``copies`` for one export; yields a
    report {"baked": [...], "skipped": [...], "seconds"}."""
    report = {"baked": [], "skipped": [], "seconds": 0.0}
    t0 = time.perf_counter()
    jobs = {}
    for obj in copies:
        if getattr(obj, "type", "") != "MESH":
            continue
        for index, material in enumerate(obj.data.materials):
            p = plan(material)
            if not p or not p["channels"]:
                continue
            job = jobs.setdefault(material.name_full, {"material": material, "plan": p, "slots": {}})
            job["slots"].setdefault(obj, set()).add(index)
    if not jobs:
        yield report
        return
    if bpy.context.mode != "OBJECT":
        report["skipped"] = [{"material": j["material"].name, "reason": "not in Object Mode"}
                             for j in jobs.values()]
        yield report
        return
    for job in list(jobs.values()):
        full = [o for o in job["slots"] if len(o.data.uv_layers) >= MAX_UV_LAYERS]
        for o in full:
            del job["slots"][o]
        if not job["slots"]:
            report["skipped"].append({"material": job["material"].name,
                                      "reason": f"its meshes already have {MAX_UV_LAYERS} UV maps"})
            del jobs[job["material"].name_full]
    if not jobs:
        yield report
        return

    scene = bpy.context.scene
    state = _render_state(scene)
    objs = list({o: None for job in jobs.values() for o in job["slots"]})
    current = {(o, i): m for o in objs for i, m in enumerate(o.data.materials)}
    original = dict(current)
    created_mats, created_images, export_mats = [], [], {}
    try:
        try:
            _bake_all(jobs, objs, scene, state, current, report, created_mats, created_images,
                      export_mats, t0, density, max_px, margin, budget_s)
        except Exception as exc:  # noqa: BLE001 - the export goes ahead unbaked
            done = {b["material"] for b in report["baked"]}
            report["skipped"] += [{"material": j["material"].name,
                                   "reason": f"bake setup failed: {type(exc).__name__}: {exc}"[:200]}
                                  for j in jobs.values() if j["material"].name not in done]
            report["baked"] = []
            for (o, i), m in original.items():
                o.data.materials[i] = m
            _restore_render(scene, state)
        report["seconds"] = round(time.perf_counter() - t0, 2)
        yield report
    finally:
        if scene.render.engine != state["engine"]:
            _restore_render(scene, state)
        for (o, i), m in original.items():
            try:
                o.data.materials[i] = m
            except Exception:  # noqa: BLE001 - a copy already removed
                pass
        for mat in created_mats:
            try:
                if mat.users == 0:
                    bpy.data.materials.remove(mat)
            except ReferenceError:
                pass
        for image in created_images:
            try:
                if image.users == 0:
                    bpy.data.images.remove(image)
            except ReferenceError:
                pass


def _use_baked(job, images, current, report, created_mats, export_mats, *, reused):
    mat = _export_material(job, images)
    created_mats.append(mat)
    export_mats[mat] = images
    for o, idx in job["slots"].items():
        for i in idx:
            current[(o, i)] = mat
    report["baked"].append({"material": job["material"].name, "objects": len(job["slots"]),
                            "channels": [_SUFFIX[c] for c in images], "px": job["size"],
                            "reused": reused})


def _bake_all(jobs, objs, scene, state, current, report, created_mats, created_images,
              export_mats, t0, density, max_px, margin, budget_s):
    base = _add_bake_layers(objs)
    _unwrap(objs, list(jobs.values()))
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 4
    if hasattr(scene.cycles, "use_denoising"):
        scene.cycles.use_denoising = False
    sink, sink_image = _sink()
    created_mats.append(sink)
    created_images.append(sink_image)
    # Textures an earlier export already baked are reused first and cost no
    # budget, so an export cut short continues where it stopped.
    pending = []
    for job in jobs.values():
        area = sum(_face_area(o, idx) for o, idx in job["slots"].items())
        job["size"] = texture_size(area, density, hi=max_px)
        job["cache_key"] = bake_cache.key(job, job["size"], margin)
        images = bake_cache.load(job["cache_key"], job["material"].name, job["plan"]["channels"],
                                 _SUFFIX, _SRGB, created_images)
        if images is None:
            pending.append(job)
            continue
        _use_baked(job, images, current, report, created_mats, export_mats, reused=True)
    for job in pending:
        name = job["material"].name
        if time.perf_counter() - t0 > budget_s:
            report["skipped"].append({"material": name, "reason": (
                f"over the {int(budget_s)} s bake budget; export again: baked materials are "
                "reused, so the next export bakes the rest")})
            continue
        bake_mat = job["material"].copy()
        bake_mat.name = f"{name}_mixar_bake"
        created_mats.append(bake_mat)
        job["bake_material"] = bake_mat
        for o in job["slots"]:
            for i in range(len(o.data.materials)):
                o.data.materials[i] = bake_mat if i in job["slots"][o] else sink
        try:
            images = _bake_channels(job, job["size"], margin, created_images)
            for image in images.values():
                image.pack()
            bake_cache.store(job["cache_key"], images, _SUFFIX)
            _use_baked(job, images, current, report, created_mats, export_mats, reused=False)
        except Exception as exc:  # noqa: BLE001 - one material's failure skips it
            report["skipped"].append({"material": name, "reason": f"{type(exc).__name__}: {exc}"[:200]})
        finally:
            for o in job["slots"]:
                for i in range(len(o.data.materials)):
                    o.data.materials[i] = current[(o, i)]
    # A copy whose every material came from the cache was never touched above.
    for (o, i), mat in current.items():
        o.data.materials[i] = mat
    _restore_render(scene, state)
    _finish_uvs(objs, base)
    names = {n for n in base.values() if n}
    if len(names) == 1:
        _relabel(export_mats, names.pop())
    else:
        # Different map names per copy: a UV node naming one would miss
        # the others, so the baked textures follow each copy's render map.
        for mat in export_mats:
            for node in list(mat.node_tree.nodes):
                if node.bl_idname == "ShaderNodeUVMap":
                    mat.node_tree.nodes.remove(node)
                elif node.bl_idname == "ShaderNodeNormalMap":
                    node.uv_map = ""
