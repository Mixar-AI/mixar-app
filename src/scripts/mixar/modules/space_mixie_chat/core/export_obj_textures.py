# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Texture staging for OBJ exports.

Blender's OBJ exporter writes a ``map_Kd`` line only for images that have a
file on disk; packed or generated images (every Mixar paint bake) silently
drop out of the ``.mtl``. ``staged_obj_textures`` writes every image the
exported materials use into ``<stem>_textures/`` beside the OBJ — packed
bytes verbatim with their real extension, on-disk files copied, only
generated images rendered to PNG (``stage_image``) —,
points the image nodes at those copies for the duration of the export
(``path_mode='RELATIVE'`` then references ``<stem>_textures/<name>.png``),
and restores the nodes and removes the copies in ``finally``. The user's
images are never modified.
"""

from __future__ import annotations

import os
import re
import shutil
from contextlib import contextmanager

import bpy

from .export_preflight import _walk_nodes, material_images


def _safe_file_stem(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.splitext(str(name or "texture"))[0]).strip("._")
    return (stem or "texture")[:96]


def textures_folder(obj_path: str) -> str:
    """``<stem>_textures`` beside the OBJ, made unique when it already exists."""
    folder, name = os.path.split(obj_path)
    stem = os.path.splitext(name)[0]
    candidate = os.path.join(folder, f"{stem}_textures")
    index = 2
    while os.path.exists(candidate):
        candidate = os.path.join(folder, f"{stem}_textures_{index}")
        index += 1
    return candidate


_FORMAT_EXTENSIONS = {
    "PNG": ".png", "JPEG": ".jpg", "JPEG2000": ".jp2", "TARGA": ".tga", "TARGA_RAW": ".tga",
    "BMP": ".bmp", "TIFF": ".tif", "OPEN_EXR": ".exr", "OPEN_EXR_MULTILAYER": ".exr",
    "HDR": ".hdr", "WEBP": ".webp", "DDS": ".dds", "CINEON": ".cin", "DPX": ".dpx",
}


def _source_file(image) -> str:
    """Absolute on-disk file of an unpacked image, or ''."""
    filepath = str(getattr(image, "filepath", "") or "")
    if not filepath:
        return ""
    if filepath.startswith("//"):
        try:
            filepath = bpy.path.abspath(filepath)
        except Exception:
            return ""
    return filepath if os.path.isfile(filepath) else ""


def _extension_for(image, source: str) -> str:
    ext = os.path.splitext(source or str(getattr(image, "filepath", "") or ""))[1].lower()
    if ext:
        return ext
    return _FORMAT_EXTENSIONS.get(str(getattr(image, "file_format", "") or "").upper(), ".png")


def has_content(image) -> bool:
    """Packed bytes or an on-disk file count even when Blender cannot decode
    the pixels (a DDS reports "does not have any image data" yet ships fine);
    a generated image needs pixels to render."""
    packed = getattr(image, "packed_file", None)
    if packed is not None and getattr(packed, "data", None):
        return True
    if _source_file(image):
        return True
    return bool(getattr(image, "size", (0, 0))[0])


def stage_image(image, folder: str, stem: str) -> str:
    """Write ``image`` beside the OBJ WITHOUT re-encoding when its bytes
    already exist: a packed image's ``packed_file.data`` verbatim (Blender
    has no writer for DDS and friends), an unpacked image's file copied;
    only a generated / filepath-less image is rendered to PNG."""
    packed = getattr(image, "packed_file", None)
    data = getattr(packed, "data", None) if packed is not None else None
    if data:
        target = os.path.join(folder, stem + _extension_for(image, ""))
        with open(target, "wb") as handle:
            handle.write(bytes(data))
        return target
    source = _source_file(image)
    if source:
        target = os.path.join(folder, stem + _extension_for(image, source))
        shutil.copyfile(source, target)
        return target
    target = os.path.join(folder, stem + ".png")
    cp = image.copy()
    cp.filepath_raw = target
    cp.file_format = "PNG"
    try:
        cp.save()
    finally:
        bpy.data.images.remove(cp)
    return target


def _materials(meshes):
    materials = []
    for mesh in meshes:
        for material in getattr(mesh.data, "materials", ()) or ():
            if material is not None and material not in materials:
                materials.append(material)
    return materials


@contextmanager
def staged_obj_textures(meshes, obj_path: str):
    """Yield ``(staged_count, folder_basename)`` with the images redirected."""
    materials = _materials(meshes)
    images = []
    for material in materials:
        for image in material_images(material):
            if image not in images and has_content(image):
                images.append(image)
    if not images:
        yield 0, ""
        return
    folder = textures_folder(obj_path)
    os.makedirs(folder, exist_ok=True)
    copies: dict = {}
    swapped: list = []
    try:
        used = set()
        for image in images:
            stem = _safe_file_stem(image.name)
            while stem in used:
                stem += "_"
            used.add(stem)
            target = stage_image(image, folder, stem)
            # The OBJ exporter resolves image.filepath (a packed image's is
            # not the file just written): reference the staged file through
            # a plain on-disk image instead.
            loaded = bpy.data.images.load(target)
            loaded.name = f"{image.name}_objtex"
            copies[image] = loaded
        for material in materials:
            for node in _walk_nodes(getattr(material, "node_tree", None)):
                image = getattr(node, "image", None)
                if image is not None and image in copies:
                    swapped.append((node, image))
                    node.image = copies[image]
        yield len(copies), os.path.basename(folder)
    finally:
        for node, image in reversed(swapped):
            try:
                node.image = image
            except Exception:
                pass
        for cp in copies.values():
            try:
                bpy.data.images.remove(cp)
            except Exception:
                pass
