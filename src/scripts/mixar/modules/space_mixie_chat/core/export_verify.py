# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Post-write verification of an exported file (agent export contract §5).

``verify_export(path, fmt, expected)`` runs while the client still knows
the path and returns a content-free ``Verification`` dict: what the FILE
contains (meshes, materials, images, clips, bounds) plus ``issues`` — human
sentences describing every mismatch against ``expected``. It never raises:
a method that cannot run reports ``checked: False`` with the reason in
``issues``. GLB / glTF are parsed directly; FBX / USD / USDZ are re-imported
into a throwaway collection (``export_reimport``); OBJ is text-scanned.
STL is re-imported too and additionally reports ``bounds`` in the FILE's
units (after the export scale) plus a non-manifold edge count.
"""

from __future__ import annotations

import json
import os
import struct
import zipfile

from .export_gltf_bounds import gltf_world_bounds

# Text formats are legitimately tiny (a cube OBJ is ~900 bytes); binaries
# below half a KB have no geometry at all.
MIN_FILE_BYTES = {"obj": 64, "gltf": 64, "stl": 134}  # STL: header + one triangle
MIN_FILE_BYTES_DEFAULT = 512
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".tga", ".tif", ".tiff", ".exr", ".bmp")


def _blank(method: str) -> dict:
    return {
        "checked": False, "method": method, "file_size_bytes": 0,
        "meshes": None, "nodes": None, "materials": [], "images": None,
        "images_embedded": None, "animations": [], "triangles": None,
        "dimensions_m": None, "up_axis": None, "draco": None,
        "issues": [], "passed": False,
    }


def _method_for(fmt: str) -> str:
    if fmt in ("glb", "gltf"):
        return "gltf_json"
    if fmt == "usdz":
        return "usdz_zip"
    if fmt == "obj":
        return "obj_text"
    return "reimport"


def verify_export(path: str, fmt: str, expected: dict | None = None) -> dict:
    """Inspect the written file and compare it with ``expected``."""
    fmt = str(fmt or "").lower().lstrip(".")
    expected = dict(expected or {})
    result = _blank(_method_for(fmt))
    try:
        result["file_size_bytes"] = os.path.getsize(path)
    except OSError:
        result["issues"].append("The exported file could not be read back.")
        return result
    try:
        floor = MIN_FILE_BYTES.get(fmt, MIN_FILE_BYTES_DEFAULT)
        if result["file_size_bytes"] < floor:
            result["issues"].append(f"The exported file is empty (under {floor} bytes).")
        if fmt == "glb":
            _verify_glb(path, result)
        elif fmt == "gltf":
            _verify_gltf(path, result)
        elif fmt == "obj":
            _verify_obj(path, result)
        elif fmt in ("fbx", "usd", "usdc", "usda", "usdz", "stl"):
            from .export_reimport import verify_by_reimport
            if fmt == "usdz":
                _usdz_listing(path, result)
            verify_by_reimport(path, fmt, result, expected.get("stl_scale"))
        else:
            result["issues"].append(f"No verification method for {fmt or 'this'} files.")
            return result
        if result["checked"]:
            _compare(result, expected, fmt)
    except Exception as exc:  # noqa: BLE001 — verification must never break an export
        result["checked"] = False
        result["issues"].append(
            f"Verification failed to run ({exc.__class__.__name__})."
        )
    result["passed"] = bool(result["checked"] and not result["issues"])
    return result


# ---------------------------------------------------------------------------
# glTF / GLB
# ---------------------------------------------------------------------------


def read_glb_json(path: str) -> dict:
    """Return the JSON chunk of a GLB; raises ValueError on a bad container."""
    with open(path, "rb") as handle:
        header = handle.read(12)
        if len(header) < 12:
            raise ValueError("truncated GLB header")
        magic, _version, _length = struct.unpack("<4sII", header)
        if magic != b"glTF":
            raise ValueError("not a GLB container")
        chunk = handle.read(8)
        if len(chunk) < 8:
            raise ValueError("missing GLB JSON chunk")
        chunk_length, chunk_type = struct.unpack("<II", chunk)
        if chunk_type != 0x4E4F534A:  # b"JSON"
            raise ValueError("first GLB chunk is not JSON")
        return json.loads(handle.read(chunk_length).decode("utf-8"))


def summarize_gltf(doc: dict, result: dict) -> None:
    """Fill ``result`` from a parsed glTF document (shared by GLB and .gltf)."""
    meshes = doc.get("meshes") or []
    images = doc.get("images") or []
    accessors = doc.get("accessors") or []
    result["meshes"] = len(meshes)
    result["nodes"] = len(doc.get("nodes") or [])
    result["materials"] = [str(m.get("name", "")) for m in doc.get("materials") or []]
    result["images"] = len(images)
    result["images_embedded"] = (
        all("bufferView" in img or str(img.get("uri", "")).startswith("data:")
            for img in images) if images else None
    )
    result["animations"] = [str(a.get("name", "")) for a in doc.get("animations") or []]
    extensions = doc.get("extensionsUsed") or []
    result["draco"] = "KHR_draco_mesh_compression" in extensions
    result["up_axis"] = "+Y"
    scenes = doc.get("scenes") or []
    result["scenes"] = len(scenes)
    if len(scenes) > 1:
        result["issues"].append(
            f"The file holds {len(scenes)} scenes; only the active scene should be exported.")
    triangles = 0
    for mesh in meshes:
        for prim in mesh.get("primitives") or []:
            mode = prim.get("mode", 4)
            index = prim.get("indices")
            position = (prim.get("attributes") or {}).get("POSITION")
            count = None
            if index is not None and index < len(accessors):
                count = accessors[index].get("count")
            elif position is not None and position < len(accessors):
                count = accessors[position].get("count")
            if count and mode == 4:
                triangles += int(count) // 3
            elif count and mode in (5, 6):
                triangles += max(0, int(count) - 2)
    result["triangles"] = triangles
    # World-space: node transforms place the parts (a 54-part rifle is not
    # the size of its largest part).
    bounds = gltf_world_bounds(doc)
    if bounds is not None:
        result["dimensions_m"] = [round(float(bounds[1][i] - bounds[0][i]), 4) for i in range(3)]
    result["checked"] = True


def _verify_glb(path: str, result: dict) -> None:
    try:
        doc = read_glb_json(path)
    except (ValueError, OSError, UnicodeDecodeError, struct.error) as exc:
        result["issues"].append(f"The GLB container is not readable ({exc}).")
        return
    summarize_gltf(doc, result)


def _verify_gltf(path: str, result: dict) -> None:
    try:
        with open(path, encoding="utf-8") as handle:
            doc = json.load(handle)
    except (OSError, ValueError) as exc:
        result["issues"].append(f"The glTF document is not readable ({exc.__class__.__name__}).")
        return
    summarize_gltf(doc, result)
    folder = os.path.dirname(path)
    missing = 0
    for entry in list(doc.get("buffers") or []) + list(doc.get("images") or []):
        uri = str(entry.get("uri") or "")
        if not uri or uri.startswith("data:"):
            continue
        if not os.path.isfile(os.path.join(folder, uri.replace("/", os.sep))):
            missing += 1
    if missing:
        result["issues"].append(
            f"{missing} file(s) referenced by the glTF are missing beside it.")


# ---------------------------------------------------------------------------
# OBJ
# ---------------------------------------------------------------------------


def _verify_obj(path: str, result: dict) -> None:
    folder = os.path.dirname(path)
    vertices = faces = objects = 0
    triangles = 0
    materials, mtl_files = [], []
    lo, hi = [None] * 3, [None] * 3
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith("v "):
                vertices += 1
                parts = line.split()
                if len(parts) >= 4:
                    try:
                        coords = [float(parts[1]), float(parts[2]), float(parts[3])]
                    except ValueError:
                        continue
                    for axis in range(3):
                        lo[axis] = coords[axis] if lo[axis] is None else min(lo[axis], coords[axis])
                        hi[axis] = coords[axis] if hi[axis] is None else max(hi[axis], coords[axis])
            elif line.startswith("f "):
                faces += 1
                triangles += max(0, len(line.split()) - 3)
            elif line.startswith("o "):
                objects += 1
            elif line.startswith("usemtl "):
                name = line[7:].strip()
                if name and name not in materials:
                    materials.append(name)
            elif line.startswith("mtllib "):
                mtl_files.append(line[7:].strip())
    result["meshes"] = objects if objects else (1 if faces else 0)
    result["nodes"] = result["meshes"]
    result["materials"] = materials
    result["triangles"] = triangles
    result["animations"] = []
    result["images_embedded"] = False
    if None not in lo and None not in hi:
        result["dimensions_m"] = [round(hi[i] - lo[i], 4) for i in range(3)]
    images = 0
    for mtl in mtl_files:
        mtl_path = os.path.join(folder, mtl)
        if not os.path.isfile(mtl_path):
            result["issues"].append("The .mtl material file is missing beside the OBJ.")
            continue
        with open(mtl_path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                token = line.strip().split(" ", 1)
                if len(token) == 2 and token[0].lower().startswith("map_"):
                    images += 1
                    if not _mtl_texture_exists(folder, token[1].strip()):
                        result["issues"].append(
                            "A texture referenced by the .mtl is missing beside the OBJ.")
    result["images"] = images
    if not faces:
        result["issues"].append("The OBJ holds vertices but no faces." if vertices
                                else "The OBJ contains no geometry (no faces).")
    result["checked"] = True


def _mtl_texture_exists(folder: str, spec: str) -> bool:
    """``map_Kd [options] path`` — the path may hold spaces, so try the whole
    remainder first, then the last token (options are rare from Blender)."""
    candidates = [spec, spec.split()[-1] if spec.split() else spec]
    for tex in candidates:
        if os.path.isabs(tex):
            return os.path.isfile(tex)
        if os.path.isfile(os.path.join(folder, tex.replace("/", os.sep))):
            return True
    return False


# ---------------------------------------------------------------------------
# USDZ
# ---------------------------------------------------------------------------


def _usdz_listing(path: str, result: dict) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
    except (zipfile.BadZipFile, OSError):
        result["issues"].append("The USDZ archive is not a readable zip.")
        return
    usd_entries = [n for n in names if n.lower().endswith((".usdc", ".usda", ".usd"))]
    textures = [n for n in names if n.lower().endswith(_IMAGE_EXTS)]
    if not usd_entries:
        result["issues"].append("The USDZ archive holds no USD layer.")
    result["images"] = len(textures)
    result["images_embedded"] = bool(textures) if textures else None


# ---------------------------------------------------------------------------
# comparison with what the exporter expected
# ---------------------------------------------------------------------------


def clip_in_file(name: str, file_names) -> bool:
    """FBX re-imports name actions ``<armature>|<stack>|<clip>``; a scene clip
    is in the file when a file name equals it or ends with ``|<clip>``."""
    wanted = str(name).lower()
    for candidate in file_names or ():
        lowered = str(candidate).lower()
        if lowered == wanted or lowered.endswith("|" + wanted):
            return True
    return False


def file_clip_names(scene_names, file_names) -> list:
    """The scene names present in the file (in file order), then any file clip
    that matches no scene name, verbatim."""
    out = []
    for candidate in file_names or ():
        hit = next((n for n in scene_names or () if clip_in_file(n, [candidate])), None)
        value = hit if hit is not None else str(candidate)
        if value not in out:
            out.append(value)
    return out


def _compare(result: dict, expected: dict, fmt: str) -> None:
    issues = result["issues"]
    want_meshes = expected.get("mesh_count")
    if expected.get("joined"):
        want_meshes = 1
    if want_meshes is not None and result.get("meshes") is not None:
        if int(result["meshes"]) != int(want_meshes):
            issues.append(
                f"The file holds {result['meshes']} mesh(es); {want_meshes} were expected.")
    clips = expected.get("clips")
    if clips:
        # Some exporters bake every clip into one animation named after the
        # object or track; only flag a clip when the file has fewer animations
        # than requested AND its name is nowhere in the list.
        missing = [name for name in clips if not clip_in_file(name, result.get("animations"))]
        if missing and len(result.get("animations") or []) < len(clips):
            issues.append(
                f"{len(missing)} requested clip(s) are not in the file.")
    images_expected = int(expected.get("images_expected") or 0)
    if images_expected and result.get("images") is not None:
        if result["images"] == 0:
            issues.append(f"{images_expected} texture(s) were expected but the file has none.")
        elif fmt == "glb" and result.get("images_embedded") is False:
            issues.append("Textures are referenced by path instead of embedded in the GLB.")
    if expected.get("compression", "none") == "none" and result.get("draco"):
        issues.append("Draco compression is on but the export asked for none.")
