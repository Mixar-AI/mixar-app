# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Cycles side of ``bake_run``: unwrap, proxies, passes, images and the
baked materials. Runs only in the background bake process, on a temporary
copy (nothing here is restored for the user's sake; the copy is deleted).

Colour, roughness, metallic and emission are baked with an EMISSION
STAND-IN: the material's own source socket is wired into an Emission shader
that drives the output, and an EMIT pass captures it exactly. A Diffuse
Color pass would read black on a metal and lit values elsewhere. The normal
pass bakes the real surface in tangent space against ``MixarBake``. The
shading keeps reading the mesh's original UVs (they stay active for render),
while the bake writes into the active ``MixarBake``.
"""

from __future__ import annotations

import os
import tempfile

import bpy
import numpy as np

from . import bake_plan
from .bake_run import BAKE_UV, JPEG_QUALITY

_proxies: list = []


def mesh_users(objects, names) -> dict:
    users = {}
    for obj in objects:
        data = getattr(obj, "data", None)
        if getattr(obj, "type", "") == 'MESH' and data is not None and data.name in names:
            users.setdefault(data.name, []).append(obj)
    return users


def setup_cycles(scene) -> str:
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = 4
    scene.cycles.use_denoising = False
    scene.render.bake.margin = 2  # under half the 0.003 island gap at 2048 px
    device = "CPU"
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for kind in ("OPTIX", "CUDA", "METAL", "HIP", "ONEAPI"):
            try:
                prefs.compute_device_type = kind
            except TypeError:
                continue
            prefs.get_devices()
            gpus = [d for d in prefs.devices if d.type == kind]
            if gpus:
                for d in prefs.devices:
                    d.use = d.type == kind
                device = kind
                break
    except Exception:
        device = "CPU"
    scene.cycles.device = 'GPU' if device != "CPU" else 'CPU'
    return device


# --- UVs --------------------------------------------------------------------------

def _select(objects, active=None):
    for obj in bpy.context.view_layer.objects:
        obj.select_set(False)
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = active or objects[0]


def _bake_layer(mesh):
    layer = mesh.uv_layers.get(BAKE_UV) or mesh.uv_layers.new(name=BAKE_UV, do_init=False)
    render = next((uv for uv in mesh.uv_layers if uv.active_render), None)
    mesh.uv_layers.active = layer
    if render is not None and render.name != BAKE_UV:
        render.active_render = True  # shading keeps the original UVs
    return layer


def unwrap(scene, meshes) -> None:
    """One joint Smart UV Project + pack over every mesh of the chunk."""
    if bpy.context.object is not None and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for obj in meshes:
        _bake_layer(obj.data)
    _select(meshes)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=1.15, island_margin=0.003, scale_to_bounds=False)
    bpy.ops.uv.select_all(action='SELECT')
    bpy.ops.uv.pack_islands(margin=0.003, rotate=True)
    bpy.ops.object.mode_set(mode='OBJECT')


def read_uv(mesh):
    data = mesh.uv_layers[BAKE_UV].data
    out = np.empty(len(data) * 2, np.float32)
    data.foreach_get("uv", out)
    return out


def set_uv(mesh, values) -> None:
    layer = _bake_layer(mesh)
    if len(values) != len(layer.data) * 2:
        raise ValueError(f"cached UVs do not fit {mesh.name}")
    layer.data.foreach_set("uv", np.asarray(values, np.float32))


# --- proxies ------------------------------------------------------------------------

def _uv_signature(mesh):
    render = next((uv.name for uv in mesh.uv_layers if uv.active_render), "")
    return tuple(uv.name for uv in mesh.uv_layers), render


def bake_objects(scene, meshes) -> list:
    """What each pass bakes: one world-space proxy per UV signature for the
    joinable meshes, and the object-relative meshes in place."""
    from .bake_attrs import add_attributes
    solo, groups = [], {}
    for obj in meshes:
        if any(bake_plan.material_verdict(m)["in_place"] for m in bake_plan._materials(obj)):
            add_attributes(obj, obj.data)  # its materials may be rewired too
            solo.append(obj)
        else:
            groups.setdefault(_uv_signature(obj.data), []).append(obj)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    targets = list(solo)
    for (_names, render), members in sorted(groups.items()):
        parts = []
        for obj in members:
            mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph), preserve_all_data_layers=True,
                                                   depsgraph=depsgraph)
            add_attributes(obj, mesh, texspace=obj.data)  # object space, before the move
            mesh.transform(obj.matrix_world)
            part = bpy.data.objects.new("mixar_bake_proxy", mesh)
            scene.collection.objects.link(part)
            parts.append(part)
        _proxies.extend(parts)
        if len(parts) > 1:
            _select(parts)
            bpy.ops.object.join()
        proxy = bpy.context.view_layer.objects.active if len(parts) > 1 else parts[0]
        proxy.data.uv_layers.active = proxy.data.uv_layers[BAKE_UV]
        if render and render in proxy.data.uv_layers:
            proxy.data.uv_layers[render].active_render = True
        targets.append(proxy)
    return targets


def cleanup_proxies() -> None:
    for obj in list(_proxies):
        try:
            mesh = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if mesh is not None and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        except ReferenceError:
            pass
    _proxies.clear()


# --- stand-ins and passes ---------------------------------------------------------------

def _principled(material):
    _output, surface = bake_plan._principled(material)
    return surface if getattr(surface, "type", "") == 'BSDF_PRINCIPLED' else None


def emits(material) -> bool:
    bsdf = _principled(material)
    if bsdf is None:
        return False
    strength, colour = bsdf.inputs["Emission Strength"], bsdf.inputs["Emission Color"]
    if not strength.is_linked and float(strength.default_value) <= 0.0:
        return False
    return colour.is_linked or any(float(c) > 0.0 for c in tuple(colour.default_value)[:3])


def _feed(tree, source, target):
    """Wire ``source`` (a Principled input) into ``target``: its link, or
    its constant."""
    if source.is_linked:
        tree.links.new(source.links[0].from_socket, target)
        return
    value = source.default_value
    try:
        rgb = tuple(value)[:3]
    except TypeError:
        rgb = (float(value),) * 3
    if target.type == 'RGBA':
        target.default_value = (*rgb, 1.0)
    else:
        target.default_value = rgb[0]


class _StandIns:
    """Temporarily drive every material's output with the channel ``kind``
    and give it an active Image Texture target (``image``)."""

    def __init__(self, materials, kind, image):
        self.kind, self.image, self.undo = kind, image, []
        self.materials = materials

    def __enter__(self):
        for material in self.materials:
            tree = material.node_tree
            output, _surface = bake_plan._principled(material)
            target = tree.nodes.new("ShaderNodeTexImage")
            target.image = self.image
            tree.nodes.active = target
            added, old = [target], None
            if self.kind != "normal" and output is not None:
                emission = tree.nodes.new("ShaderNodeEmission")
                added.append(emission)
                bsdf = _principled(material)
                emission.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
                emission.inputs["Strength"].default_value = 1.0
                if bsdf is not None:
                    names = {"color": ("Base Color",), "rough": ("Roughness",), "metal": ("Metallic",),
                             "emit": ("Emission Color", "Emission Strength")}[self.kind]
                    _feed(tree, bsdf.inputs[names[0]], emission.inputs["Color"])
                    if len(names) > 1:
                        if emits(material):
                            _feed(tree, bsdf.inputs[names[1]], emission.inputs["Strength"])
                        else:
                            emission.inputs["Strength"].default_value = 0.0
                surface = output.inputs["Surface"]
                old = surface.links[0].from_socket if surface.is_linked else None
                tree.links.new(emission.outputs["Emission"], surface)
            self.undo.append((tree, output, old, added))
        return self

    def __exit__(self, *_exc):
        for tree, output, old, added in reversed(self.undo):
            if old is not None:
                tree.links.new(old, output.inputs["Surface"])
            for node in added:
                tree.nodes.remove(node)
        return False


def _bake(scene, targets, materials, kind, image) -> None:
    with _StandIns(materials, kind, image):
        for index, obj in enumerate(targets):
            for other in scene.objects:
                other.hide_render = other is not obj
            _select([obj])
            if kind == "normal":
                bpy.ops.object.bake(type='NORMAL', normal_space='TANGENT', use_clear=index == 0,
                                    margin=scene.render.bake.margin)
            else:
                bpy.ops.object.bake(type='EMIT', use_clear=index == 0, margin=scene.render.bake.margin)


def _new_image(name, res, float_buffer, colorspace):
    image = bpy.data.images.new(name, res, res, alpha=False, float_buffer=float_buffer)
    image.colorspace_settings.name = colorspace
    return image


def _pixels(image):
    out = np.empty(image.size[0] * image.size[1] * 4, np.float32)
    image.pixels.foreach_get(out)
    return out.reshape(image.size[1], image.size[0], 4)


def _save(image, path, fmt):
    image.filepath_raw = path
    image.file_format = fmt
    try:
        image.save(filepath=path, quality=JPEG_QUALITY)
    except TypeError:
        image.save()


def _from_pixels(name, pixels, colorspace, path, fmt):
    h, w = pixels.shape[:2]
    image = _new_image(name, w, False, colorspace)
    image.pixels.foreach_set(np.ascontiguousarray(pixels, np.float32).ravel())
    _save(image, path, fmt)
    bpy.data.images.remove(image)


def bake_chunk(scene, chunk, index, progress) -> tuple[dict, dict]:
    """Bake one chunk; ``(files, meta)`` with files in a temp directory."""
    meshes, res = chunk["meshes"], chunk["res"]
    materials = sorted({m for obj in meshes for m in bake_plan._materials(obj)}, key=lambda m: m.name)
    from .bake_attrs import carry_inputs
    carry_inputs([m for m in materials if bake_plan.material_verdict(m)["object_relative"]])
    targets = bake_objects(scene, meshes)
    folder = tempfile.mkdtemp(prefix="mixar-bake-")
    files, meta = {}, {"res": res, "normal": False, "emit": False, "emit_strength": 0.0,
                       "emitters": sorted(m.name for m in materials if emits(m))}
    passes = [("color", 0.0), ("rough", 0.25), ("metal", 0.45)]
    if any(_principled(m) is not None and _principled(m).inputs["Normal"].is_linked for m in materials):
        passes.append(("normal", 0.6))
    if meta["emitters"]:
        passes.append(("emit", 0.8))
    baked = {}
    for kind, at in passes:
        progress(at, f"Baking {kind} ({res} px)")
        image = _new_image(f"mixar_bake_{index}_{kind}", res, kind in ("rough", "metal", "emit"),
                           "sRGB" if kind == "color" else "Non-Color")
        _bake(scene, targets, materials, kind, image)
        baked[kind] = image
    colour = _pixels(baked["color"])
    _from_pixels("c", colour, "sRGB", os.path.join(folder, "color.jpg"), 'JPEG')
    files["color.jpg"] = os.path.join(folder, "color.jpg")
    orm = np.ones_like(colour)
    orm[..., 1] = _pixels(baked["rough"])[..., 0]
    orm[..., 2] = _pixels(baked["metal"])[..., 0]
    _from_pixels("o", np.clip(orm, 0.0, 1.0), "Non-Color", os.path.join(folder, "orm.jpg"), 'JPEG')
    files["orm.jpg"] = os.path.join(folder, "orm.jpg")
    if "normal" in baked:
        _from_pixels("n", _pixels(baked["normal"]), "Non-Color", os.path.join(folder, "normal.jpg"), 'JPEG')
        files["normal.jpg"] = os.path.join(folder, "normal.jpg")
        meta["normal"] = True
    if "emit" in baked:
        light = _pixels(baked["emit"])
        k = float(light[..., :3].max())
        if k > 1e-6:
            light[..., :3] /= k
            light[..., :3] = np.where(light[..., :3] <= 0.0031308, light[..., :3] * 12.92,
                                      1.055 * np.clip(light[..., :3], 0, 1) ** (1 / 2.4) - 0.055)
            light[..., 3] = 1.0
            _from_pixels("e", light, "sRGB", os.path.join(folder, "emit.png"), 'PNG')
            files["emit.png"] = os.path.join(folder, "emit.png")
            meta.update(emit=True, emit_strength=round(k, 4))
    for image in baked.values():
        bpy.data.images.remove(image)
    cleanup_proxies()
    progress(1.0, "Baked")
    return files, meta


# --- applying a bake ------------------------------------------------------------------

def load_images(entry: str, index: int) -> dict:
    import json
    with open(os.path.join(entry, "meta.json"), encoding="utf-8") as handle:
        meta = json.load(handle)
    images = {"meta": meta}
    for name, key, colorspace in (("color.jpg", "color", "sRGB"), ("orm.jpg", "orm", "Non-Color"),
                                  ("normal.jpg", "normal", "Non-Color"), ("emit.png", "emit", "sRGB")):
        path = os.path.join(entry, name)
        if os.path.isfile(path):
            image = bpy.data.images.load(path, check_existing=False)
            image.name = f"mixar_bake_{index}_{key}"
            image.colorspace_settings.name = colorspace
            images[key] = image
    return images


def apply_cached(chunk, entry: str) -> dict:
    uvs = np.load(os.path.join(entry, "uvs.npz"))
    for obj in chunk["meshes"]:
        set_uv(obj.data, uvs[obj.data.name])
    return load_images(entry, chunk.get("index", 0))


def _baked_material(material, index, images):
    """A Principled material reading chunk ``index``'s images via MixarBake."""
    baked = bpy.data.materials.new(f"{material.name}")
    baked.use_nodes = True
    tree = baked.node_tree
    tree.nodes.clear()
    out = tree.nodes.new("ShaderNodeOutputMaterial")
    bsdf = tree.nodes.new("ShaderNodeBsdfPrincipled")
    tree.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    uv = tree.nodes.new("ShaderNodeUVMap")
    uv.uv_map = BAKE_UV

    def tex(image):
        node = tree.nodes.new("ShaderNodeTexImage")
        node.image = image
        tree.links.new(uv.outputs["UV"], node.inputs["Vector"])
        return node

    tree.links.new(tex(images["color"]).outputs["Color"], bsdf.inputs["Base Color"])
    split = tree.nodes.new("ShaderNodeSeparateColor")
    tree.links.new(tex(images["orm"]).outputs["Color"], split.inputs["Color"])
    tree.links.new(split.outputs["Green"], bsdf.inputs["Roughness"])
    tree.links.new(split.outputs["Blue"], bsdf.inputs["Metallic"])
    if "normal" in images:
        normal = tree.nodes.new("ShaderNodeNormalMap")
        normal.uv_map = BAKE_UV
        tree.links.new(tex(images["normal"]).outputs["Color"], normal.inputs["Color"])
        tree.links.new(normal.outputs["Normal"], bsdf.inputs["Normal"])
    meta = images["meta"]
    if "emit" in images and material.name in meta.get("emitters", ()):
        tree.links.new(tex(images["emit"]).outputs["Color"], bsdf.inputs["Emission Color"])
        bsdf.inputs["Emission Strength"].default_value = float(meta["emit_strength"])
    original = _principled(material)
    if original is not None and not original.inputs["Alpha"].is_linked:
        bsdf.inputs["Alpha"].default_value = original.inputs["Alpha"].default_value
    return baked


def assign(chunk, index, images, users) -> None:
    """Point every user of the chunk's mesh data at the baked materials and
    make ``MixarBake`` the mesh's only UV map."""
    made = {}
    for obj in chunk["meshes"]:
        for user in users.get(obj.data.name, [obj]):
            for slot in user.material_slots:
                material = slot.material
                if material is None:
                    continue
                if material.name not in made:
                    made[material.name] = _baked_material(material, index, images)
                slot.material = made[material.name]
        mesh = obj.data
        mesh.uv_layers[BAKE_UV].active_render = True
        mesh.uv_layers.active = mesh.uv_layers[BAKE_UV]
        for layer in [uv for uv in mesh.uv_layers if uv.name != BAKE_UV]:
            mesh.uv_layers.remove(layer)
