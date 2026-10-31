# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Export packages for the agent's ``export_asset`` tool (contract §2):
GLB / glTF / FBX / USD(Z) + ``textures/`` + ``manifest.json`` + optional
lower-resolution texture tiers, a ``.blend`` source and a README.

Exports run on temporary copies (transforms and modifiers applied, parents
flattened, optionally joined), so the user's objects are never changed.
Mixar paint slots on the copies are swapped to their baked Principled/image
materials (``export_materials``) for the whole package; an unbaked stack
still ships untextured.
Destinations are NAMED (downloads, documents, desktop, project,
mixar_exports); results report file names relative to the package folder,
never an absolute local path. The written main file is verified with
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

from .export_clips import animation_kwargs, clip_selection, select_clips
from .export_materials import temporary_export_materials
from .export_verify import file_clip_names, verify_export

FORMATS = ("glb", "gltf", "fbx", "usdz", "usd")
DESTINATIONS = ("mixar_exports", "downloads", "documents", "desktop", "project")
GENERATOR = "Mixar export_package"
_LEGACY_GENERATORS = (GENERATOR, "Mixar uv_bake.export_package")


def _safe(name, fallback="asset"):
    s = re.sub(r"[^A-Za-z0-9._ -]+", "_", str(name or "")).strip(" .")
    return (s or fallback)[:96]


_project_folder_override = None   # set in a worker: the user's folder, not the snapshot's
_telemetry_enabled = True          # a worker leaves telemetry to the app


def set_project_folder(folder) -> None:
    """In a worker process, ``bpy.data.filepath`` is the snapshot: ``project``
    must mean the folder of the user's own saved file ("" = unsaved)."""
    global _project_folder_override
    _project_folder_override = None if folder is None else str(folder)


def set_telemetry_enabled(enabled: bool) -> None:
    global _telemetry_enabled
    _telemetry_enabled = bool(enabled)


def _project_folder() -> str:
    if _project_folder_override is not None:
        return _project_folder_override
    return os.path.dirname(bpy.data.filepath) if bpy.data.filepath else ""


def destination(where, subfolder=None):
    """Absolute folder for a named destination (created)."""
    where = (where or "mixar_exports").lower()
    if where not in DESTINATIONS:
        raise ValueError(f"destination must be one of {DESTINATIONS}")
    home = os.path.expanduser("~")
    if where == "project" and _project_folder():
        base = _project_folder()
    elif where == "downloads":
        base = os.path.join(home, "Downloads")
    elif where == "desktop":
        base = os.path.join(home, "Desktop")
    elif where == "documents":
        base = os.path.join(home, "Documents")
    else:
        base = os.path.join(home, "Documents", "Mixar Exports")
    path = os.path.join(base, _safe(subfolder)) if subfolder else base
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


def _copies(objs, join):
    """World-baked, parent-free, modifier-applied mesh copies. Self-cleaning:
    a failure part-way undoes the renames and drops the temp collection, so
    the user's objects never keep the ``.mixar_export_src`` name."""
    deps = bpy.context.evaluated_depsgraph_get()
    col = bpy.data.collections.new("mixar_export_tmp")
    bpy.context.scene.collection.children.link(col)
    out = []
    renamed = []
    try:
        for o in objs:
            # the copy takes the original's name so exported node names are clean
            orig = o.name
            o.name = orig + ".mixar_export_src"
            renamed.append((o, orig))
            ev = o.evaluated_get(deps)
            me = bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=True, depsgraph=deps)
            me.transform(o.matrix_world)
            if o.matrix_world.is_negative:
                me.flip_normals()
            c = bpy.data.objects.new(orig, me)
            for idx, slot in enumerate(o.material_slots):
                if slot.link == "OBJECT" and slot.material is not None and idx < len(me.materials):
                    me.materials[idx] = slot.material
            col.objects.link(c)
            out.append(c)
        if join and len(out) > 1:
            ctx = {"active_object": out[0], "selected_editable_objects": out, "selected_objects": out}
            with bpy.context.temp_override(**ctx):
                bpy.ops.object.join()
            out = [out[0]]
    except Exception:
        _cleanup(col, renamed)
        raise
    return col, out, renamed


def _cleanup(col, renamed):
    for o in list(col.objects):
        me = o.data
        bpy.data.objects.remove(o)
        if me is not None and me.users == 0:
            bpy.data.meshes.remove(me)
    bpy.data.collections.remove(col)
    for o, orig in renamed:
        o.name = orig


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


def _select_only(objs):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]


def exporter_kwargs(fmt, animations=None):
    """The package exporter's fixed settings plus the clip request."""
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
    anim, mode, warning = animation_kwargs(fmt, animations)
    kw.update(anim)
    return kw, mode, warning


def _export(fmt, path, objs, animations=None):
    _select_only(objs)
    kw, mode, warning = exporter_kwargs(fmt, animations)
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


def _bounds(objs):
    import numpy as np
    pts = []
    for o in objs:
        co = np.empty(len(o.data.vertices) * 3)
        o.data.vertices.foreach_get("co", co)
        pts.append(co.reshape(-1, 3))
    p = np.concatenate(pts) if pts else np.zeros((1, 3))
    return (p.max(0) - p.min(0)).tolist()


def _telemetry(event, fmt, **props):
    if not _telemetry_enabled:
        return
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
                   extra_files=(), animations=None):
    """``include_source`` may be True or a file name for the .blend; ``readme``
    text is written as README.md; ``extra_files`` are (name, text) pairs;
    ``animations`` is None (all) / [] (none) / [clip names].

    Called by the agent's script (the GUI executor), the package is built in a
    background worker process on a snapshot of the document and the call
    returns ``{"__deferred_job__": key}``: the executor holds the reply open and
    answers it with this function's ordinary return value when the worker is
    done (``poll_job``). Elsewhere, or when no worker can run, it is built here.
    """
    kwargs = {"names": list(names), "fmt": fmt, "filename": filename, "where": where,
              "folder": folder, "join": join, "texture_tiers": list(texture_tiers or ()),
              "include_source": include_source, "manifest": manifest, "readme": readme,
              "extra_files": [list(x) for x in extra_files or ()], "animations": animations}
    deferred = _submit_to_worker(kwargs)
    if deferred is not None:
        return deferred
    return _export_in_process(**kwargs)


def _export_in_process(names, fmt="glb", filename=None, where="mixar_exports", folder=None,
                       join=False, texture_tiers=(), include_source=False, manifest=True,
                       readme=None, extra_files=(), animations=None):
    """The package itself, built from this process's data (the app's, or a
    worker's snapshot)."""
    t0 = time.perf_counter()
    fmt = fmt.lower()
    if fmt not in FORMATS:
        raise ValueError(f"format must be one of {FORMATS}")
    scene = bpy.context.scene
    objs = [scene.objects[n] for n in names]
    stem = _safe(os.path.splitext(filename or objs[0].name)[0])
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
    clips, clips_missing = select_clips(armatures, animations)
    col, copies, renamed = _copies(meshes, join)
    swap = ExitStack()
    try:
        # Mixar paint slots on the COPIES become their baked Principled/image
        # materials first, so the file, textures/, tiers, the .blend source
        # and the manifest all describe what an exporter can read.
        swap.enter_context(temporary_export_materials(copies))
        mats = []
        for c in copies:
            for s in c.material_slots:
                if s.material and s.material not in mats:
                    mats.append(s.material)
        images = _material_images(mats)
        main = os.path.join(root, stem + ext)
        exported = list(copies) + armatures
        with clip_selection(armatures, animations, scene) as (clips, clips_missing):
            anim_mode, warning = _export(fmt, main, exported, animations)
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
                    _export(fmt, os.path.join(root, tier_name), exported, animations)
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
        verification = verify_export(main, fmt, {
            "mesh_count": len(copies), "armature_count": len(armatures),
            "clips": clips if animations is not None else None,
            "joined": bool(join and len(meshes) > 1), "images_expected": len(images),
            "compression": "none",
        })
        if verification.get("checked") and verification.get("animations") and animations is None:
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
                   use_case="package", destination_kind=where,
                   mesh_count=len(copies), armature_count=len(armatures),
                   clip_count=len(clips), duration_ms=duration_ms,
                   delivery_status=verification_status(verification),
                   verification_checked=bool(verification and verification.get("checked")),
                   verification_passed=bool(verification and verification.get("passed")),
                   issue_count=len((verification or {}).get("issues") or []),
                   file_size_kb=int((verification or {}).get("file_size_bytes", 0) // 1024))
    return {"delivery_status": verification_status(verification),
            "warning": verification_warning(verification), "destination": where,
            "folder": os.path.basename(root), "files": files,
            "replaced_previous_files": replaced,
            "main_file": stem + ext, "glb_check": check, "verification": verification,
            "triangles": tris, "dimensions_m": dims, "textures": len(tex), "tiers": tiers,
            "animations": {"clips": clips, "clips_requested": animations,
                           "clips_missing": clips_missing, "mode": anim_mode,
                           "warning": warning},
            "seconds": round(time.perf_counter() - t0, 2)}


# ---------------------------------------------------------------------------
# Out of process: the package built by a background Mixar worker
# ---------------------------------------------------------------------------
#
# A package applies modifiers to copies (``new_from_object``, which crashed the
# app on a dangling material), swaps materials, bakes and writes files: minutes
# of main-thread work on a heavy scene, all of it in the user's process. Here
# the same ``_export_in_process`` runs in a worker on a snapshot. The files go
# to the same named destination; the user's scene, selection and names are
# never touched (the copies' ``.mixar_export_src`` renames happen in the
# snapshot). A worker that never starts builds it here after all; a package
# that crashes two workers fails with a plain message, never the app.

#: The backend waits PACKAGE_TIMEOUT_S (600 s) for the reply.
WORKER_REPLY_MAX_S = 590.0
WORKER_TIMEOUT_S = 580.0
_worker_jobs = {}    # key -> {"worker", "snapshot", "kwargs", "scene", "view_layer", ...}
_last_worker = {}


def last_worker_job() -> dict:
    return dict(_last_worker)


def _worker_allowed() -> bool:
    if bpy.app.background:
        return False
    try:
        from . import main_thread_executor
        if not main_thread_executor.accepts_deferred_jobs():
            return False
        from mixar.modules.common.render_worker import supervisor
        return supervisor.available()
    except Exception:
        return False


def _validate(kwargs):
    """The errors the in-process build raises before it changes anything, so a
    bad call fails the same way, at once."""
    fmt = str(kwargs["fmt"]).lower()
    if fmt not in FORMATS:
        raise ValueError(f"format must be one of {FORMATS}")
    scene = bpy.context.scene
    objs = [scene.objects[n] for n in kwargs["names"]]
    if not [o for o in objs if o.type == "MESH"]:
        raise ValueError("names must include at least one mesh object")
    destination(kwargs["where"])  # an unknown destination raises here


def _submit_to_worker(kwargs):
    if not _worker_allowed():
        return None
    _validate(kwargs)
    import uuid
    from mixar.modules.common.render_worker import snapshot, supervisor
    started = time.perf_counter()
    try:
        record = snapshot.write("export")
    except Exception:
        return None
    key = uuid.uuid4().hex
    out = os.path.join(supervisor.root_dir(), "jobs", "export-%s.json" % key)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    scene = bpy.context.scene
    view_layer = bpy.context.view_layer
    try:
        job_id = supervisor.submit("export", {
            "kind": "export", "snapshot": record["path"], "images": record["images"],
            "scene": scene.name, "view_layer": getattr(view_layer, "name", ""),
            "params": {"kwargs": kwargs, "project_dir": _project_folder()}, "out": out},
            timeout_s=WORKER_TIMEOUT_S)
    except Exception:
        snapshot.remove_folder(record["folder"])
        return None
    snapshot.acquire(record)
    _worker_jobs[key] = {"worker": job_id, "snapshot": record, "kwargs": kwargs, "scene": scene,
                         "view_layer": getattr(view_layer, "name", ""), "out": out,
                         "started": time.perf_counter()}
    _last_worker.clear()
    _last_worker.update(key=key, job=job_id, state="running", snapshot_bytes=record["bytes"],
                        snapshot_save_s=record["save_s"], snapshot_images_s=record["images_s"],
                        dirty_images=record["image_count"],
                        submit_s=round(time.perf_counter() - started, 4))
    _telemetry("initiated", str(kwargs["fmt"]).lower())
    return {"__deferred_job__": key}


def _completed_telemetry(job, result):
    kwargs = job["kwargs"]
    fmt = str(kwargs["fmt"]).lower()
    verification = result.get("verification") if isinstance(result.get("verification"), dict) else None
    _telemetry("completed", fmt, success=bool(result.get("success")),
               extension={"glb": ".glb", "gltf": ".gltf", "fbx": ".fbx", "usdz": ".usdz",
                          "usd": ".usdc"}.get(fmt, ""),
               scope="named", use_case="package", destination_kind=kwargs["where"],
               duration_ms=int((time.perf_counter() - job["started"]) * 1000),
               delivery_status=verification_status(verification),
               verification_checked=bool(verification and verification.get("checked")),
               verification_passed=bool(verification and verification.get("passed")),
               issue_count=len((verification or {}).get("issues") or []),
               file_size_kb=int((verification or {}).get("file_size_bytes", 0) // 1024),
               out_of_process=True)


def _in_process_now(job) -> dict:
    """The worker never started: build the package here, in the call's scene."""
    scene = job["scene"]
    try:
        overrides = {"scene": scene}
        layer = scene.view_layers.get(job["view_layer"])
        if layer is not None:
            overrides["view_layer"] = layer
        window = next(iter(bpy.context.window_manager.windows), None)
        if window is not None:
            overrides["window"] = window
        with bpy.context.temp_override(**overrides):
            result = _export_in_process(**job["kwargs"])
        result["success"] = True
    except ReferenceError:
        result = {"success": False, "error": "the scene was closed before the export ran"}
    except Exception as exc:
        result = {"success": False, "error": type(exc).__name__ + ": " + str(exc)}
    return result


_WORKER_ERRORS = {
    "worker_crashed": "the background export process crashed twice on this package; "
                      "the app and the scene are unaffected",
    "worker_timeout": "the background export did not finish in time and was stopped",
    "worker_job_failed": "the background export process could not run this package",
    "scene_unavailable": "the scene was not found in the export snapshot",
}


def poll_job(key) -> dict:
    """``{"status": "running"}`` or ``{"status": "done", "result": <reply>}``
    for a worker package (``preview_deferral.defer_job``)."""
    import json
    from mixar.modules.common.render_worker import snapshot, supervisor
    job = _worker_jobs.get(key)
    if job is None:
        return {"status": "done", "result": {"success": False, "error": "export job not found"}}
    state = supervisor.poll(job["worker"])
    if state["state"] in ("queued", "running"):
        return {"status": "running"}
    _worker_jobs.pop(key, None)
    supervisor.forget(job["worker"])
    snapshot.release(job["snapshot"])
    _last_worker.update(state=state["state"], error=state.get("error", ""),
                        attempts=state.get("attempts"), pid=state.get("pid"),
                        retried_after_crash=state.get("retried_after_crash"),
                        worker_seconds=state.get("seconds"),
                        elapsed_s=round(time.perf_counter() - job["started"], 3))
    result = None
    if state["state"] == "done":
        try:
            with open(state["out"], encoding="utf-8") as handle:
                result = json.load(handle)
        except (OSError, ValueError):
            result = None
        try:
            os.remove(state["out"])
        except OSError:
            pass
    elif state.get("error") == "worker_unavailable":
        _last_worker["fallback"] = "in_process"
        # The in-process build reports its own telemetry.
        return {"status": "done", "result": _in_process_now(job)}
    if not isinstance(result, dict):
        message = _WORKER_ERRORS.get(state.get("error"), "the background export failed")
        result = {"success": False, "error": "RuntimeError: " + message}
    _completed_telemetry(job, result)
    return {"status": "done", "result": result}


def cancel_job(key) -> None:
    from mixar.modules.common.render_worker import snapshot, supervisor
    job = _worker_jobs.pop(key, None)
    if job is None:
        return
    supervisor.cancel(job["worker"])
    supervisor.forget(job["worker"])
    snapshot.release(job["snapshot"])
