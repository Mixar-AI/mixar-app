# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Image to 3D Utilities

Helper functions for downloading and importing 3D models from URLs.
"""

import bpy
import os
import tempfile
import urllib.request
from typing import Optional

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def download_and_import_glb(url: str) -> list:
    """
    Download a GLB file from URL and import it into Blender.

    Args:
        url: URL to the GLB file

    Returns:
        List of imported objects
    """
    logger.debug("[Image to 3D] Downloading model...")

    # Download the file
    with urllib.request.urlopen(url, timeout=60) as response:
        model_bytes = response.read()

    logger.debug("[Image to 3D] Downloaded %s bytes", len(model_bytes))

    # Write to temp file
    with tempfile.NamedTemporaryFile(suffix='.glb', delete=False) as f:
        f.write(model_bytes)
        temp_path = f.name

    try:
        # Track existing objects
        existing_objects = set(bpy.data.objects.keys())

        # Import GLB
        bpy.ops.import_scene.gltf(filepath=temp_path)

        # Find newly imported objects
        new_objects = [
            bpy.data.objects[name]
            for name in bpy.data.objects.keys()
            if name not in existing_objects
        ]

        logger.debug("[Image to 3D] Imported %s objects", len(new_objects))

        # Select and frame the new objects
        bpy.ops.object.select_all(action='DESELECT')
        for obj in new_objects:
            obj.select_set(True)
            if obj.type == 'MESH':
                bpy.context.view_layer.objects.active = obj

        return new_objects

    finally:
        # Clean up temp file
        try:
            os.unlink(temp_path)
        except OSError:
            pass


def download_and_import_model(url: str, file_format: str = "glb") -> list:
    """
    Download a model from URL and import based on format.

    Supports: glb, fbx, obj, stl, usdz

    Args:
        url: URL to the model file
        file_format: Output format (glb, fbx, obj, stl, usdz)

    Returns:
        List of imported objects
    """
    file_format = file_format.lower()
    suffix_map = {
        "glb": ".glb",
        "gltf": ".gltf",
        "fbx": ".fbx",
        "obj": ".obj",
        "stl": ".stl",
        "usdz": ".usdz",
    }

    suffix = suffix_map.get(file_format, ".glb")
    logger.debug("[Image to 3D] Downloading %s model...", file_format.upper())

    # Download the file
    with urllib.request.urlopen(url, timeout=60) as response:
        model_bytes = response.read()

    logger.debug("[Image to 3D] Downloaded %s bytes", len(model_bytes))

    # Write to temp file
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(model_bytes)
        temp_path = f.name

    try:
        # Track existing objects
        existing_objects = set(bpy.data.objects.keys())

        # Import based on format
        if file_format in ("glb", "gltf"):
            bpy.ops.import_scene.gltf(filepath=temp_path)
        elif file_format == "fbx":
            bpy.ops.import_scene.fbx(filepath=temp_path)
        elif file_format == "obj":
            bpy.ops.wm.obj_import(filepath=temp_path)
        elif file_format == "stl":
            bpy.ops.wm.stl_import(filepath=temp_path)
        elif file_format == "usdz":
            # USDZ requires USD addon
            try:
                bpy.ops.wm.usd_import(filepath=temp_path)
            except AttributeError:
                logger.warning("[Image to 3D] USD import not available, trying as GLB")
                bpy.ops.import_scene.gltf(filepath=temp_path)
        else:
            # Default to GLB
            bpy.ops.import_scene.gltf(filepath=temp_path)

        # Find newly imported objects
        new_objects = [
            bpy.data.objects[name]
            for name in bpy.data.objects.keys()
            if name not in existing_objects
        ]

        logger.debug("[Image to 3D] Imported %s objects", len(new_objects))

        # Select and frame the new objects
        bpy.ops.object.select_all(action='DESELECT')
        for obj in new_objects:
            obj.select_set(True)
            if obj.type == 'MESH':
                bpy.context.view_layer.objects.active = obj

        return new_objects

    finally:
        # Clean up temp file
        try:
            os.unlink(temp_path)
        except OSError:
            pass


def get_model_url_from_response(data: dict) -> Optional[str]:
    """
    Extract model URL from API response data.

    Args:
        data: API response data dict

    Returns:
        Model URL or None if not found
    """
    if not isinstance(data, dict):
        return None

    # Check for nested data
    if "data" in data and isinstance(data["data"], dict):
        data = data["data"]

    # Try various keys
    return data.get("model_url") or data.get("url") or data.get("glb_url")


def get_file_format_from_url(url: str) -> str:
    """
    Determine file format from URL.

    Args:
        url: Model URL

    Returns:
        File format string (glb, fbx, obj, etc.)
    """
    url_lower = url.lower()
    if ".fbx" in url_lower:
        return "fbx"
    elif ".obj" in url_lower:
        return "obj"
    elif ".stl" in url_lower:
        return "stl"
    elif ".usdz" in url_lower:
        return "usdz"
    elif ".gltf" in url_lower:
        return "gltf"
    return "glb"  # Default
