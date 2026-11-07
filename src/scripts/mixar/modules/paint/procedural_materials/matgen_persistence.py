# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Disk persistence for AI-generated procedural materials.

Writes scripts to the user data directory (not the addon source tree) and
maintains matgen_catalog.json. All functions are pure Python; bpy is
imported lazily only inside _get_matgen_paths() for path resolution.
"""
import dataclasses
import hashlib
import json
import os
import re
import threading
from typing import Optional

from ....config.logging_config import get_logger

logger = get_logger(__name__)

_catalog_lock = threading.Lock()


@dataclasses.dataclass
class MaterialInfo:
    """Lightweight result object returned by save_generated_material."""
    material_id: str
    name: str
    category: str
    script_path: str          # absolute path to the saved .py file
    thumbnail_path: Optional[str]
    node_group_name: str
    node_group_template: None = None


def _get_matgen_paths() -> tuple:
    """Return (matgen_dir, catalog_path) rooted in the user data directory.

    Uses bpy.utils.user_resource when available (Blender runtime), falling
    back to ~/.mixar/ for standalone tests.
    """
    try:
        import bpy
        data_base = bpy.utils.user_resource('DATAFILES', path='mixar')
    except Exception:
        data_base = os.path.join(os.path.expanduser("~"), ".mixar")
    return (
        os.path.join(data_base, "matgen"),
        os.path.join(data_base, "matgen_catalog.json"),
    )


def _make_safe_filename(query: str) -> str:
    """Convert a query string to a safe, collision-resistant .py filename.

    Example: "worn copper with patina" -> "worn_copper_with_patina_a3f2.py"
    """
    safe = re.sub(r'[^a-z0-9]+', '_', query.lower()).strip('_')
    safe = safe[:40].rstrip('_')
    h = hashlib.sha256(query.encode()).hexdigest()[:4]
    return f"{safe}_{h}.py"


def _load_catalog(catalog_path: str) -> dict:
    """Load the JSON catalog, resetting if corrupted."""
    if not os.path.exists(catalog_path):
        return {"materials": []}
    try:
        with open(catalog_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "materials" not in data:
            data["materials"] = []
        return data
    except json.JSONDecodeError:
        logger.warning("matgen_catalog.json is corrupted — resetting to empty catalog")
        return {"materials": []}


def _write_catalog(catalog_path: str, data: dict) -> None:
    """Write catalog atomically (write tmp -> rename)."""
    tmp_path = catalog_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, catalog_path)


def _make_display_name(query: str) -> str:
    return query.strip().title()


def save_generated_material(
    script: str,
    query: str,
    archetype: str,
    matgen_dir: Optional[str] = None,
    catalog_path: Optional[str] = None,
) -> MaterialInfo:
    """Save a generated script to disk and update the catalog.

    Scripts are written to the user data directory, not the addon source tree,
    so they survive addon updates and work on read-only installations.

    Args:
        script: The Python material script string.
        query: The user prompt used to generate it.
        archetype: Material category hint from backend (e.g. "metal").
        matgen_dir: Override script directory (defaults to user data matgen/).
        catalog_path: Override catalog path (defaults to user data matgen_catalog.json).

    Returns:
        MaterialInfo with absolute script_path and display metadata.
    """
    _default_matgen_dir, _default_catalog_path = _get_matgen_paths()
    matgen_dir = matgen_dir or _default_matgen_dir
    catalog_path = catalog_path or _default_catalog_path

    os.makedirs(matgen_dir, exist_ok=True)
    os.makedirs(os.path.dirname(catalog_path), exist_ok=True)

    filename = _make_safe_filename(query)
    script_full_path = os.path.join(matgen_dir, filename)
    # Relative path stored in catalog: "matgen/<filename>" relative to catalog's parent dir
    script_relative_path = os.path.join("matgen", filename)

    with open(script_full_path, "w", encoding="utf-8") as f:
        f.write(script)

    display_name = _make_display_name(query)
    material_id = f"ai_generated_{filename.replace('.py', '')}"

    new_entry = {
        "material_id": material_id,
        "name": display_name,
        "category": "ai_generated",
        "material_path": script_relative_path,
        "thumbnail_path": None,
        "query": query,
        "archetype": archetype or "",
    }

    with _catalog_lock:
        catalog = _load_catalog(catalog_path)
        for i, existing in enumerate(catalog["materials"]):
            if existing.get("material_path") == script_relative_path:
                catalog["materials"][i] = new_entry
                break
        else:
            catalog["materials"].append(new_entry)
        _write_catalog(catalog_path, catalog)

    logger.info("Saved AI material '%s' to %s", display_name, script_full_path)

    return MaterialInfo(
        material_id=material_id,
        name=display_name,
        category="ai_generated",
        script_path=script_full_path,   # absolute — ready for ProceduralMaterial
        thumbnail_path=None,
        node_group_name=display_name,
    )
