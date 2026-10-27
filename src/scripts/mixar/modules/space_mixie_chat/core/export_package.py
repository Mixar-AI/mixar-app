# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Export packages for the agent's ``export_asset`` tool (contract §2):
GLB / glTF / FBX / USD(Z) + ``textures/`` + ``manifest.json`` + optional
lower-resolution texture tiers, a ``.blend`` source and a README.

Exports run on temporary copies (transforms and modifiers applied, parents
flattened, optionally joined), so the user's objects are never changed. A
skinned mesh's copy keeps its armature (parent, Armature modifier, vertex
groups) so the file still carries a skin; a named empty stands for the
meshes and armatures under it.
Mixar paint slots on the copies are swapped to their baked Principled/image
materials (``export_materials``) for the whole package; every material an
exporter cannot read (procedural nodes, an unbaked stack) is then baked to
images on the copies (``export_bake``, ``bake_materials``), reported as
``baked_materials``.
Destinations are NAMED (downloads, documents, desktop, project,
mixar_exports); results report file names relative to the package folder,
never an absolute local path. ``engine`` (``godot`` | ``unreal`` | ``uefn``,
``engine_targets``) adds collision hulls named for that engine's importer,
validates the objects' ``mixar_*`` game-semantics tags into the manifest's
``engine`` section and reports what would degrade on import. The written main file is verified with
``export_verify`` (``verification``; ``glb_check`` keeps the same dict for
GLB). ``animations`` follows ``export_clips`` — the copies are static
meshes, so clips only apply to armatures the named objects include or are
skinned to.
"""

import hashlib
import json
import os
import re
import time
from contextlib import ExitStack

import bpy

from .export_verification_status import verification_status, verification_warning

from .export_bake import baked_procedural_materials
from .export_clips import animation_kwargs, clip_selection, select_clips
from .export_materials import temporary_export_materials
from .export_verify import file_clip_names, verify_export
from . import engine_targets

FORMATS = ("glb", "gltf", "fbx", "usdz", "usd")
DESTINATIONS = ("mixar_exports", "downloads", "documents", "desktop", "project")
GENERATOR = "Mixar export_package"
_LEGACY_GENERATORS = (GENERATOR, "Mixar uv_bake.export_package")


def _safe(name, fallback="asset"):
    s = re.sub(r"[^A-Za-z0-9._ -]+", "_", str(name or "")).strip(" .")
    return (s or fallback)[:96]


def destination(where, subfolder=None, create=True):
    """Absolute folder for a named destination (created unless ``create`` is
    False — a lookup of an existing package)."""
    where = (where or "mixar_exports").lower()
    if where not in DESTINATIONS:
        raise ValueError(f"destination must be one of {DESTINATIONS}")
    home = os.path.expanduser("~")
    if where == "project" and bpy.data.filepath:
        base = os.path.dirname(bpy.data.filepath)
    elif where == "downloads":
        base = os.path.join(home, "Downloads")
    elif where == "desktop":
        base = os.path.join(home, "Desktop")
    elif where == "documents":
        base = os.path.join(home, "Documents")
    else:
        base = os.path.join(home, "Documents", "Mixar Exports")
    path = os.path.join(base, _safe(subfolder)) if subfolder else base
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def _clear_previous(root, keep=()):
    """A re-export replaces the package: remove the files the previous
    manifest in this folder lists (only files this exporter wrote, only
    inside the folder) except ``keep`` — the files the new package has just
    rewritten in place; anything else in the folder is left alone. Called
    AFTER the new files are written and BEFORE the new manifest, so a failed
    re-export leaves the previous package intact."""
    path = os.path.join(root, "manifest.json")
    if not os.path.isfile(path):
        return 0
    try:
        with open(path, encoding="utf-8") as fh:
            old = json.load(fh)
    except (OSError, ValueError):
        return 0
    if old.get("generator") not in _LEGACY_GENERATORS:
        return 0
    removed = 0
    base = os.path.realpath(root)
    kept = {os.path.realpath(os.path.join(root, rel)) for rel in keep}
    for entry in old.get("files", []):
        rel = entry.get("file") if isinstance(entry, dict) else None
        if not rel:
            continue
        target = os.path.realpath(os.path.join(root, rel))
        if target in kept or not target.startswith(base + os.sep) or not os.path.isfile(target):
            continue
        os.remove(target)
        removed += 1
    os.remove(path)
    return removed


def _material_images(mats):
    out = []

    def walk(tree, seen):
        if tree is None or tree.name_full in seen:
            return
        seen.add(tree.name_full)
        for n in tree.nodes:
            if n.bl_idname == "ShaderNodeTexImage" and n.image is not None and n.image not in out:
                out.append(n.image)
            elif n.bl_idname == "ShaderNodeGroup":
                walk(n.node_tree, seen)
    for m in mats:
        if m is not None and m.use_nodes:
            walk(m.node_tree, set())
    return out


def _copies(objs, join, keep_origins=False):
    """World-baked, parent-free, modifier-applied mesh copies. Self-cleaning:
    a failure part-way undoes the renames and drops the temp collection, so
    the user's objects never keep the ``.mixar_export_src`` name.
    ``keep_origins`` (engine packages) bakes rotation and scale but leaves each
    copy at its original's world origin, so a door turns about its hinge and a
    pickup spins about its own centre; the world placement is unchanged.

    A SKINNED mesh (parented to an armature or deformed by one) stays skinned:
    its copy applies every modifier but the Armature ones, keeps its vertex
    groups, its transform and its armature parent, and gets the same Armature
    modifiers — baking the deform would freeze it in the current pose and the
    file would carry a skeleton the mesh no longer follows. Skinned copies are
    never joined."""
    skinned = {o for o in objs if _skinned(o)}
    held = []
    for o in skinned:
        for m in o.modifiers:
            if m.type == "ARMATURE" and m.show_viewport:
                m.show_viewport = False
                held.append(m)
    col = bpy.data.collections.new("mixar_export_tmp")
    bpy.context.scene.collection.children.link(col)
    out = []
    renamed = []
    try:
        if held:
            bpy.context.view_layer.update()
        deps = bpy.context.evaluated_depsgraph_get()
        for o in objs:
            # the copy takes the original's name so exported node names are clean
            orig = o.name
            o.name = orig + ".mixar_export_src"
            renamed.append((o, orig))
            ev = o.evaluated_get(deps)
            me = bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=True, depsgraph=deps)
            if o in skinned:
                c = _skinned_copy(o, orig, me)
            else:
                me.transform(o.matrix_world)
                if o.matrix_world.is_negative:
                    me.flip_normals()
                origin = None
                if keep_origins:
                    from mathutils import Matrix
                    origin = o.matrix_world.translation.copy()
                    me.transform(Matrix.Translation(-origin))
                c = bpy.data.objects.new(orig, me)
                if origin is not None:
                    c.location = origin
            for idx, slot in enumerate(o.material_slots):
                if slot.link == "OBJECT" and slot.material is not None and idx < len(me.materials):
                    me.materials[idx] = slot.material
            col.objects.link(c)
            out.append(c)
        static = [c for c, o in zip(out, objs) if o not in skinned]
        if join and len(static) > 1:
            ctx = {"active_object": static[0], "selected_editable_objects": static, "selected_objects": static}
            with bpy.context.temp_override(**ctx):
                bpy.ops.object.join()
            out = [c for c, o in zip(out, objs) if o in skinned or c is static[0]]
    except Exception:
        _cleanup(col, renamed)
        raise
    finally:
        for m in held:
            m.show_viewport = True
        # parented (skinned) copies get their world matrix here
        bpy.context.view_layer.update()
    return col, out, renamed


def _skinned_copy(o, name, me):
    """A copy of skinned ``o`` that the exporters still write as a skin:
    the un-deformed mesh with its vertex groups, ``o``'s transform and armature
    parent, and ``o``'s Armature modifiers pointing at the same armatures."""
    c = bpy.data.objects.new(name, me)
    for vg in o.vertex_groups:
        if c.vertex_groups.get(vg.name) is None:
            c.vertex_groups.new(name=vg.name)
    if o.parent is not None:
        c.parent = o.parent
        c.parent_type = o.parent_type
        c.parent_bone = o.parent_bone
        c.matrix_parent_inverse = o.matrix_parent_inverse.copy()
        c.matrix_basis = o.matrix_basis.copy()
    else:
        c.matrix_world = o.matrix_world.copy()
    mods = [m for m in o.modifiers if m.type == "ARMATURE" and m.object is not None]
    if not mods and o.parent is not None and o.parent.type == "ARMATURE" and o.parent_type == "ARMATURE":
        mods = [None]  # parented with automatic weights: deform by the parent
    for m in mods:
        cm = c.modifiers.new("Armature", "ARMATURE")
        cm.object = o.parent if m is None else m.object
        if m is not None:
            cm.use_vertex_groups = m.use_vertex_groups
            cm.use_bone_envelopes = m.use_bone_envelopes
            cm.use_deform_preserve_volume = m.use_deform_preserve_volume
    return c


def _cleanup(col, renamed):
    for o in list(col.objects):
        me = o.data
        bpy.data.objects.remove(o)
        if me is not None and me.users == 0:
            bpy.data.meshes.remove(me)
    bpy.data.collections.remove(col)
    for o, orig in renamed:
        o.name = orig


def _expand_empties(objs, scene):
    """A named empty stands for the hierarchy under it (a generated asset's
    root, a level's group): its mesh and armature descendants in this scene
    join the export, in order, each once."""
    out = []
    for o in objs:
        group = [o] + (list(o.children_recursive) if o.type == "EMPTY" else [])
        for c in group:
            if c not in out and (c is o or (c.type in ("MESH", "ARMATURE") and c.name in scene.objects)):
                out.append(c)
    return out


def _armatures(objs):
    found = []
    for o in objs:
        candidates = [o] if o.type == "ARMATURE" else []
        if o.parent is not None and o.parent.type == "ARMATURE":
            candidates.append(o.parent)
        candidates += [m.object for m in getattr(o, "modifiers", ())
                       if m.type == "ARMATURE" and m.object is not None]
        for a in candidates:
            if a not in found:
                found.append(a)
    return found


def _skinned(obj):
    parent = getattr(obj, "parent", None)
    return (parent is not None and parent.type == "ARMATURE") or any(
        m.type == "ARMATURE" and m.object is not None for m in getattr(obj, "modifiers", ()))


def _engine_prepare(engine, copies, renamed, col, joined):
    """Game-semantics tags read off the ORIGINAL objects onto their copies, a
    collision mesh set per copy -> (manifest objects, issues, hull objects)."""
    originals = {orig: o for o, orig in renamed}
    objects, issues, hulls = [], [], []
    for c in copies:
        src = originals.get(c.name)
        tags, tag_issues = engine_targets.read_tags(src, c.name) if src is not None else ({}, [])
        issues += tag_issues
        if joined:
            for o, orig in renamed:
                if orig == c.name:
                    continue
                other, _ = engine_targets.read_tags(o, orig)
                if other and other != tags:
                    issues.append(f"{orig}: its mixar_* tags differ from {c.name}'s; "
                                  f"the joined mesh keeps {c.name}'s.")
        for key, value in tags.items():
            c[engine_targets.TAG_PREFIX + key] = value
        shape = engine_targets.collision_shape(tags, src is not None and _skinned(src))
        names = engine_targets.collision_names(engine, c.name, shape)
        hulls += engine_targets.build_collision(engine, c, shape, names, col)
        objects.append({"name": c.name, **tags, "origin": [round(float(v), 4) for v in c.matrix_world.translation],
                        "collision": engine_targets.collision_entry(engine, c.name, shape, names)})
    return objects, issues, hulls


def _select_only(objs):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]


def exporter_kwargs(fmt, animations=None, engine=None):
    """The package exporter's fixed settings plus the clip request; an
    ``engine`` package keeps custom properties (glTF node extras) and an
    Unreal-family FBX takes the ``unreal`` export preset."""
    if fmt in ("glb", "gltf"):
        kw = dict(export_format="GLB" if fmt == "glb" else "GLTF_SEPARATE",
                  use_selection=True, use_active_scene=True, export_yup=True, export_apply=True,
                  export_draco_mesh_compression_enable=False,
                  export_image_format="AUTO", export_materials="EXPORT",
                  export_tangents=True, export_cameras=False, export_lights=False)
    elif fmt == "fbx":
        kw = dict(use_selection=True, axis_forward="-Z", axis_up="Y",
                  apply_unit_scale=True, apply_scale_options="FBX_SCALE_ALL",
                  path_mode="COPY", embed_textures=True, mesh_smooth_type="FACE",
                  use_tspace=True, object_types={"MESH", "ARMATURE"}, add_leaf_bones=False)
    else:
        kw = dict(selected_objects_only=True, export_materials=True,
                  export_uvmaps=True, convert_orientation=True,
                  export_global_forward_selection="NEGATIVE_Z",
                  export_global_up_selection="Y", export_textures_mode="NEW",
                  overwrite_textures=True, relative_paths=True,
                  export_cameras=False, export_lights=False)
    if engine and fmt in ("glb", "gltf"):
        kw["export_extras"] = True
    elif engine in ("unreal", "uefn") and fmt == "fbx":
        from .export_presets import PRESETS
        kw.update(PRESETS["unreal"]["fbx"])
    anim, mode, warning = animation_kwargs(fmt, animations)
    kw.update(anim)
    return kw, mode, warning


def _export(fmt, path, objs, animations=None, engine=None):
    _select_only(objs)
    kw, mode, warning = exporter_kwargs(fmt, animations, engine)
    if fmt in ("glb", "gltf"):
        r = bpy.ops.export_scene.gltf(filepath=path, **kw)
    elif fmt == "fbx":
        r = bpy.ops.export_scene.fbx(filepath=path, **kw)
    else:
        r = bpy.ops.wm.usd_export(filepath=path, **kw)
    if "FINISHED" not in r:
        raise RuntimeError(f"{fmt} export returned {sorted(r)}")
    return mode, warning


def inspect_glb(path):
    """Read the GLB JSON chunk: counts, embedded images, extensions."""
    from .export_verify import read_glb_json
    try:
        doc = read_glb_json(path)
    except (ValueError, OSError):
        return {"valid": False}
    imgs = doc.get("images", [])
    return {"valid": True, "bytes": os.path.getsize(path),
            "meshes": len(doc.get("meshes", [])), "nodes": len(doc.get("nodes", [])),
            "materials": [m.get("name") for m in doc.get("materials", [])],
            "images": len(imgs), "images_embedded": all("bufferView" in i for i in imgs),
            "extensions_used": doc.get("extensionsUsed", []),
            "draco": "KHR_draco_mesh_compression" in doc.get("extensionsUsed", [])}


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr", ".hdr", ".bmp", ".tga", ".webp", ".psd"}
_NUMBER_SUFFIX = re.compile(r"\.\d{3,}$")


def _texture_stem(name):
    """File stem for an image datablock: drops a real image extension only,
    so ``Wood`` and ``Wood.001`` (Blender's de-duplication) stay distinct."""
    name = str(name or "")
    match = _NUMBER_SUFFIX.search(name)
    suffix = match.group(0) if match else ""
    name = name[:match.start()] if match else name
    stem, ext = os.path.splitext(name)
    if ext.lower() in _IMAGE_EXTS:
        name = stem
    return _safe(name + suffix, fallback="texture")


def _save_textures(images, folder, size=None):
    """Write PNG copies (optionally downscaled to ``size``) -> {orig: copy}.
    File names are unique per folder (a ``_2``… counter breaks any clash
    left after ``_texture_stem``'s character replacement)."""
    os.makedirs(folder, exist_ok=True)
    out = {}
    used = set()
    for img in images:
        if img.size[0] == 0:
            continue
        cp = img.copy()
        cp.name = f"{img.name}_{size}" if size else f"{img.name}_pkg"
        if size and max(img.size) > size:
            w, h = img.size
            s = size / max(w, h)
            cp.scale(max(1, int(w * s)), max(1, int(h * s)))
        stem = _texture_stem(img.name)
        fname, n = stem + ".png", 1
        while fname.lower() in used:
            n += 1
            fname = f"{stem}_{n}.png"
        used.add(fname.lower())
        cp.filepath_raw = os.path.join(folder, fname)
        cp.file_format = "PNG"
        cp.save()
        out[img] = (cp, fname)
    return out


def _swap_images(mats, mapping):
    """Point image nodes at replacement images; returns an undo list."""
    undo = []
    for m in mats:
        if m is None or not m.use_nodes:
            continue
        for n in m.node_tree.nodes:
            if n.bl_idname == "ShaderNodeTexImage" and n.image in mapping:
                undo.append((n, n.image))
                n.image = mapping[n.image][0]
    return undo


def _bake_warning(baked):
    """One line when procedural materials went out unbaked (they arrive flat)."""
    skipped = (baked or {}).get("skipped") or []
    if not skipped:
        return ""
    names = ", ".join(s["material"] for s in skipped[:8])
    return (f"{len(skipped)} procedural material(s) were not baked and will look flat in the file: "
            f"{names}. {skipped[0]['reason']}.")


def _bounds(objs):
    """World extents of the copies; a skinned copy keeps its own transform
    (its rest pose under the armature), so every copy is read in world space."""
    import numpy as np
    pts = []
    for o in objs:
        co = np.empty(len(o.data.vertices) * 3)
        o.data.vertices.foreach_get("co", co)
        m = np.array(o.matrix_world)
        pts.append(co.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3])
    p = np.concatenate(pts) if pts else np.zeros((1, 3))
    return (p.max(0) - p.min(0)).tolist()


def _telemetry(event, fmt, **props):
    try:
        from mixar.modules.common.analytics.export_events import (
            capture_export, capture_export_initiated,
        )
        if event == "initiated":
            capture_export_initiated(bpy.context, fmt, via="agent", tool="export_asset")
        else:
            capture_export(bpy.context, export_format=fmt, extension=props.pop("extension", ""),
                           success=props.pop("success"),
                           extra={"via": "agent", "tool": "export_asset", **props})
    except Exception:
        pass


def _write_source(root, stem, include_source, col, copies, mats, images):
    src_name = _safe(os.path.splitext(str(include_source))[0]) + ".blend" \
        if isinstance(include_source, str) else stem + "_source.blend"
    # The delivered world-baked copies inside one collection named after the
    # package (append that collection to get the export as delivered). No
    # Scene datablock: bpy.data.libraries.write of a Scene crashes Blender
    # 5.2 (reproduced 2026-09-23), so the file opens with its datablocks
    # ready to append.
    col.name = stem
    data = {col} | set(copies) | {c.data for c in copies} | set(mats) | set(images)
    bpy.data.libraries.write(os.path.join(root, src_name), data, fake_user=True, compress=True)
    return src_name


def export_package(names, fmt="glb", filename=None, where="mixar_exports", folder=None, join=False,
                   texture_tiers=(), include_source=False, manifest=True, readme=None,
                   extra_files=(), animations=None, engine=None, bake_materials=True):
    """``include_source`` may be True or a file name for the .blend; ``readme``
    text is written as README.md; ``extra_files`` are (name, text) pairs;
    ``animations`` is None (all) / [] (none) / [clip names]; ``engine`` is
    None or one of ``engine_targets.ENGINES``; ``bake_materials`` bakes
    procedural materials to images on the copies."""
    t0 = time.perf_counter()
    fmt = fmt.lower()
    if fmt not in FORMATS:
        raise ValueError(f"format must be one of {FORMATS}")
    if engine is not None:
        engine = engine_targets.normalise_engine(engine)
        if engine is None:
            raise ValueError(f"engine must be one of {engine_targets.ENGINES}")
        if fmt not in engine_targets.ENGINE_FORMATS[engine]:
            raise ValueError(f"a {engine} package is {' or '.join(engine_targets.ENGINE_FORMATS[engine])}")
    scene = bpy.context.scene
    named = [scene.objects[n] for n in names]
    objs = _expand_empties(named, scene)
    stem = _safe(os.path.splitext(filename or named[0].name)[0])
    root = destination(where, folder or stem)
    replaced = 0
    ext = {"glb": ".glb", "gltf": ".gltf", "fbx": ".fbx", "usdz": ".usdz", "usd": ".usdc"}[fmt]
    files = []
    _telemetry("initiated", fmt)
    meshes = [o for o in objs if o.type == "MESH"]
    if not meshes:
        raise ValueError("names must include at least one mesh object")
    armatures = _armatures(objs)
    if animations is not None:
        animations = [str(a) for a in animations]
    # Selection is captured BEFORE the copies rename the originals, or the
    # restore in ``finally`` would never match the restored names.
    prev_sel = [o.name for o in scene.objects if o.select_get()]
    prev_active = bpy.context.view_layer.objects.active
    success = False
    verification = None
    engine_section = None
    hulls = []
    clips, clips_missing = select_clips(armatures, animations)
    col, copies, renamed = _copies(meshes, join, keep_origins=bool(engine))
    swap = ExitStack()
    try:
        # Mixar paint slots on the COPIES become their baked Principled/image
        # materials first, so the file, textures/, tiers, the .blend source
        # and the manifest all describe what an exporter can read.
        swap.enter_context(temporary_export_materials(copies))
        baked = (swap.enter_context(baked_procedural_materials(copies))
                 if bake_materials and fmt in ("glb", "gltf", "fbx", "usdz", "usd") else None)
        mats = []
        for c in copies:
            for s in c.material_slots:
                if s.material and s.material not in mats:
                    mats.append(s.material)
        images = _material_images(mats)
        main = os.path.join(root, stem + ext)
        engine_objects, engine_issues = [], []
        if engine:
            engine_objects, engine_issues, hulls = _engine_prepare(
                engine, copies, renamed, col, bool(join and len(meshes) > 1))
        exported = list(copies) + hulls + armatures
        with clip_selection(armatures, animations, scene) as (clips, clips_missing):
            anim_mode, warning = _export(fmt, main, exported, animations, engine)
        files.append(stem + ext)
        tex = _save_textures(images, os.path.join(root, "textures"))
        files += [f"textures/{f}" for _, f in tex.values()]
        for cp, _ in tex.values():
            bpy.data.images.remove(cp)
        tiers = []
        for size in texture_tiers or ():
            size = int(size)
            low = _save_textures(images, os.path.join(root, f"textures_{size}"), size)
            undo = _swap_images(mats, low)
            try:
                tier_name = f"{stem}_{size}{ext}"
                with clip_selection(armatures, animations, scene):
                    _export(fmt, os.path.join(root, tier_name), exported, animations, engine)
            finally:
                for node, img in undo:
                    node.image = img
                for cp, _ in low.values():
                    bpy.data.images.remove(cp)
            files.append(tier_name)
            files += [f"textures_{size}/{f}" for _, f in low.values()]
            tiers.append({"max_texture_px": size, "file": tier_name})
        if include_source:
            files.append(_write_source(root, stem, include_source, col, copies, mats, images))
        for name, text in [("README.md", readme)] + [tuple(x) for x in extra_files or ()]:
            if text:
                with open(os.path.join(root, _safe(name)), "w", encoding="utf-8") as fh:
                    fh.write(str(text))
                files.append(_safe(name))
        if engine:
            engine_issues += engine_targets.readiness_issues(
                engine,
                textures=[(f"textures/{f}", tuple(img.size)) for img, (_, f) in tex.items()],
                meshes=[(c.name, bool(c.data.uv_layers),
                         bool(_material_images([s.material for s in c.material_slots])))
                        for c in copies],
                objects=engine_objects)
            engine_section = engine_targets.manifest_section(engine, engine_objects, engine_issues)
        verification = verify_export(main, fmt, {
            "mesh_count": len(copies), "extra_meshes": len(hulls), "armature_count": len(armatures),
            "skinned_meshes": sum(1 for c in copies if _skinned(c)),
            "clips": clips if animations is not None else None,
            "joined": bool(join and len(meshes) > 1), "images_expected": len(images),
            "compression": "none",
        })
        # The clips reported are the ones the FILE holds, requested or not.
        if verification.get("checked") and (verification.get("animations") or animations):
            clips = file_clip_names(clips, verification["animations"])
        warning = " ".join(filter(None, (warning, verification_warning(verification))))
        check = verification if fmt == "glb" else None
        tris = sum(sum(len(p.vertices) - 2 for p in c.data.polygons) for c in copies)
        dims = [round(x, 4) for x in _bounds(copies)]
        info = {
            "asset": stem, "format": fmt, "up_axis": "+Y", "units": "meters",
            "transforms_applied": True, "compression": "none", "objects": [orig for _, orig in renamed],
            "joined": bool(join and len(meshes) > 1), "triangles": tris, "dimensions_m": dims,
            "materials": [m.name for m in mats],
            "textures": [{"file": f"textures/{f}", "size": list(img.size)} for img, (_, f) in tex.items()],
            "animations": clips, "tiers": tiers, "files": [], "generator": GENERATOR,
        }
        if engine_section is not None:
            info["engine"] = engine_section
        if baked and (baked["baked"] or baked["skipped"]):
            info["baked_materials"] = baked
        for f in files:
            p = os.path.join(root, f)
            info["files"].append({"file": f, "bytes": os.path.getsize(p), "sha256_16": _sha(p)})
        # Only now is the previous package dropped: the new files are all on
        # disk, and the old manifest is still the one on disk to read.
        replaced = _clear_previous(root, keep=files)
        if manifest:
            with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8") as fh:
                json.dump(info, fh, indent=2)
            files.append("manifest.json")
        success = True
    finally:
        swap.close()
        _cleanup(col, renamed)
        for o in scene.objects:
            o.select_set(o.name in prev_sel)
        if prev_active is not None and prev_active.name in scene.objects:
            bpy.context.view_layer.objects.active = prev_active
        duration_ms = int((time.perf_counter() - t0) * 1000)
        _telemetry("completed", fmt, success=success, extension=ext, scope="named",
                   use_case="package", destination_kind=where, engine=engine or "",
                   mesh_count=len(copies), armature_count=len(armatures),
                   clip_count=len(clips), duration_ms=duration_ms,
                   delivery_status=verification_status(verification),
                   verification_checked=bool(verification and verification.get("checked")),
                   verification_passed=bool(verification and verification.get("passed")),
                   issue_count=len((verification or {}).get("issues") or []),
                   file_size_kb=int((verification or {}).get("file_size_bytes", 0) // 1024))
    return {"delivery_status": verification_status(verification),
            "warning": " ".join(filter(None, (verification_warning(verification), _bake_warning(baked)))),
            "destination": where,
            "folder": os.path.basename(root), "files": files,
            "replaced_previous_files": replaced, "engine": engine_section,
            "main_file": stem + ext, "glb_check": check, "verification": verification,
            "triangles": tris, "dimensions_m": dims, "textures": len(tex), "tiers": tiers,
            "baked_materials": baked,
            "animations": {"clips": clips, "clips_requested": animations,
                           "clips_missing": clips_missing, "mode": anim_mode,
                           "warning": warning},
            "seconds": round(time.perf_counter() - t0, 2)}
