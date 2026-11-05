# SPDX-FileCopyrightText: 2026 Mixar AI
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
import os
import json
import queue as _queue
import threading
from typing import Dict, List, Tuple, Optional

from ....config.logging_config import get_logger
from .script_preprocessor import _fix_rgb_to_rgba, _safe_set_default_value
from .matgen_fetcher import _get_auth_token, _get_base_url, _get_cache_dir

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Async script fetcher — replaces blocking _fetch_script_blocking
# ---------------------------------------------------------------------------

def _fetch_script_async(material_id: str, cache_file: str, material_name: str) -> None:
    """Kick off a background fetch and cache the result to cache_file.

    On success, writes the script to cache_file and triggers a UI redraw so
    the next get_node_group() call finds it in the disk cache.  Returns
    immediately — caller must return None and let the UI retry.
    """
    result_queue = _queue.Queue()

    def _fetch():
        token = _get_auth_token()
        base_url = _get_base_url()
        if not token or not base_url:
            result_queue.put({"ok": False, "error": "not authenticated"})
            return
        try:
            from .matgen_client import fetch_script_async as _client_fetch
            _client_fetch(material_id, token, base_url, result_queue)
        except Exception as exc:
            result_queue.put({"ok": False, "error": str(exc)})

    threading.Thread(target=_fetch, daemon=True).start()

    def _on_result():
        try:
            result = result_queue.get_nowait()
        except _queue.Empty:
            return 0.25  # reschedule

        if result.get("ok"):
            script_text = result.get("script", "")
            try:
                with open(cache_file, 'w', encoding='utf-8') as f:
                    f.write(script_text)
                logger.info("Cached script for '%s'", material_name)
            except Exception as exc:
                logger.warning("Failed to write cache for %s: %s", material_id, exc)
            # Trigger redraw — next get_node_group() call will find the disk cache
            try:
                for window in bpy.context.window_manager.windows:
                    for area in window.screen.areas:
                        area.tag_redraw()
            except Exception:
                pass
        else:
            logger.error(
                "Could not fetch script for '%s': %s",
                material_name, result.get("error"),
            )
        return None  # unregister timer

    bpy.app.timers.register(_on_result, first_interval=0.25)


# ---------------------------------------------------------------------------
# ProceduralMaterial
# ---------------------------------------------------------------------------

class ProceduralMaterial:
    """Represents a custom procedural material.

    Can be backed by a local file (script_path) or by server-fetched text
    (script). When neither is available, get_node_group() triggers a
    background fetch and returns None (non-blocking).
    """

    def __init__(self, material_id: str, name: str, category: str,
                 script_path: str = None, thumbnail_path: str = None,
                 node_group_name: str = None, script: str = None,
                 thumbnail_url: str = None):
        self.material_id = material_id
        self.name = name
        self.category = category
        self.script_path = script_path       # local .py file (legacy / local mode)
        self.script = script                 # script text (server / DB mode)
        self.thumbnail_path = thumbnail_path  # local image file path
        self.thumbnail_url = thumbnail_url   # CDN/S3 URL
        self.node_group_name = node_group_name or name
        self.node_group_template = None

    def __repr__(self):
        return f"ProceduralMaterial(id={self.material_id}, name={self.name}, category={self.category})"


# ---------------------------------------------------------------------------
# MaterialRegistry
# ---------------------------------------------------------------------------

class MaterialRegistry:
    """Registry for managing procedural materials."""

    def __init__(self):
        self._materials: Dict[str, ProceduralMaterial] = {}
        self._categories: Dict[str, List[ProceduralMaterial]] = {}
        self._loaded = False
        self._lock = threading.RLock()

    def register_material(self, material: ProceduralMaterial):
        with self._lock:
            if material.material_id in self._materials:
                old_mat = self._materials[material.material_id]
                if old_mat.category in self._categories:
                    self._categories[old_mat.category] = [
                        m for m in self._categories[old_mat.category]
                        if m.material_id != material.material_id
                    ]
            self._materials[material.material_id] = material
            if material.category not in self._categories:
                self._categories[material.category] = []
            self._categories[material.category].append(material)

    def unregister_material(self, material_id: str):
        with self._lock:
            if material_id in self._materials:
                mat = self._materials[material_id]
                if mat.category in self._categories:
                    self._categories[mat.category] = [
                        m for m in self._categories[mat.category]
                        if m.material_id != material_id
                    ]
                del self._materials[material_id]

    def get_material(self, material_id: str) -> Optional[ProceduralMaterial]:
        with self._lock:
            return self._materials.get(material_id)

    def get_all_materials(self) -> List[ProceduralMaterial]:
        with self._lock:
            return list(self._materials.values())

    def get_categories(self) -> List[str]:
        with self._lock:
            return sorted(self._categories.keys())

    def get_materials_by_category(self, category: str) -> List[ProceduralMaterial]:
        with self._lock:
            return list(self._categories.get(category, []))

    def get_material_items(self) -> List[Tuple[str, str, str]]:
        with self._lock:
            return [(mat.material_id, mat.name, '') for mat in self._materials.values()]

    def is_custom_material(self, layer_type: str) -> bool:
        with self._lock:
            return layer_type in self._materials

    def get_node_group(self, material_id: str):
        """Get or create the node group for a material.

        Execution priority:
        1. Already in bpy.data.node_groups — return immediately.
        2. script text set — execute from text.
        3. script_path set and file exists — execute from file.
        4. Disk cache hit — load and execute.
        5. Neither — trigger async server fetch; return None (non-blocking).
           Caller will retry after the next UI redraw.
        """
        material = self.get_material(material_id)
        if not material:
            return None

        # 1. Already created
        node_group = bpy.data.node_groups.get(material.node_group_name)
        if node_group:
            return node_group

        # 2. Script text available
        if material.script:
            return self._execute_material_script(material)

        # 3. Local file available
        if material.script_path and os.path.exists(material.script_path):
            return self._execute_material_script(material)

        # 4. Disk cache
        cache_dir = _get_cache_dir()
        cache_file = os.path.join(cache_dir, f"{material_id}.py")
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    material.script = f.read()
                logger.debug("Loaded script for '%s' from disk cache", material.name)
                return self._execute_material_script(material)
            except Exception as exc:
                logger.warning("Failed to read cached script for %s: %s", material_id, exc)

        # 5. Script not cached — caller must trigger a fetch explicitly.
        return None

    def _execute_material_script(self, material: ProceduralMaterial):
        """Execute a material script (from text or file) and return the node group."""
        try:
            existing_materials = set(bpy.data.materials)
            existing_node_groups = set(bpy.data.node_groups)

            import math as _math_module
            _mathutils_module = __import__('mathutils')

            # Server-fetched material code is untrusted input, so it runs under
            # the same sandbox stack as chat agent scripts: the chat sandbox's
            # vetted builtins dict (getattr/hasattr/setattr wrapped to block
            # dunder access) plus the dunders-only AST validator below. The
            # legacy hand-rolled whitelist here admitted object/getattr/super,
            # whose chains walk to real builtins (object.__subclasses__() ->
            # os) — a full escape for unsigned MatGen server code. Class-
            # hierarchy helpers are dropped; none of the bundled material
            # scripts use them.
            from mixar.modules.space_mixie_chat.core.sandbox_builtins import (
                get_safe_builtins,
            )
            from mixar.modules.space_mixie_chat.core.sandbox_bpy import (
                make_sandboxed_bpy,
            )
            from mixar.modules.space_mixie_chat.core.sandbox_modules import (
                safe_module,
            )

            _ALLOWED_IMPORTS = {
                # Same guarded surface as the chat sandbox: script.python_file_run
                # would execute files with REAL builtins, bypassing everything.
                # safe_module too: bpy.utils._os is the real os module.
                'bpy': make_sandboxed_bpy(safe_module(bpy)),
                'mathutils': _mathutils_module,
                'math': _math_module,
            }

            def _safe_import(name, *args, **kwargs):
                if name in _ALLOWED_IMPORTS:
                    return _ALLOWED_IMPORTS[name]
                raise ImportError(f"Import of '{name}' is not allowed in material scripts")

            _SAFE_MATERIAL_BUILTINS = get_safe_builtins()
            # Deliberately absent from the namespace: os, subprocess, runpy and
            # open grant filesystem/execution capability; object/super/property/
            # staticmethod/classmethod enable the class-hierarchy escape the
            # wrapped getattr cannot see. Pop them so a future builtins change
            # cannot silently re-admit them.
            for _danger in ('object', 'super', 'property', 'staticmethod',
                            'classmethod', 'os', 'subprocess', 'runpy', 'open'):
                _SAFE_MATERIAL_BUILTINS.pop(_danger, None)
            _SAFE_MATERIAL_BUILTINS['__import__'] = _safe_import

            exec_globals = {
                'bpy': _ALLOWED_IMPORTS['bpy'],
                'mathutils': _mathutils_module,
                'math': _math_module,
                '__builtins__': _SAFE_MATERIAL_BUILTINS,
                '__name__': '__main__',
                # Safe setter for indexed socket inputs — handles Color vs Vector
                # socket ambiguity in generated scripts (see script_preprocessor.py).
                '_safe_set_default_value': _safe_set_default_value,
            }

            # Get script text — prefer in-memory text, fall back to file
            if material.script:
                material_code = material.script
            else:
                with open(material.script_path, 'r', encoding='utf-8') as f:
                    material_code = f.read()

            material_code = _fix_rgb_to_rgba(material_code)

            # Same dunders-only scan the chat sandbox runs before exec — blocks
            # introspection escape chains (object.__subclasses__() etc.) before
            # any code runs. Validated AFTER the preprocessor rewrite, so the
            # exact text that would be exec'd is what gets scanned.
            from mixar.modules.space_mixie_chat.core.sandbox_validator import (
                validate_script_ast,
            )
            violation = validate_script_ast(material_code)
            if violation:
                logger.error(
                    "Material script blocked by sandbox for '%s':\n%s",
                    material.name, violation,
                )
                return None

            try:
                exec(material_code, exec_globals)  # noqa: S102 - intentional sandboxed exec
            except Exception as _exec_err:
                logger.warning(
                    "Script exec error for '%s' (will check for partial results): %s",
                    material.name, _exec_err,
                )

            _build_called = False
            if 'create_material' in exec_globals and callable(exec_globals['create_material']):
                try:
                    exec_globals['create_material']()
                except Exception as _cm_err:
                    logger.warning(
                        "create_material() error for '%s' (checking partial results): %s",
                        material.name, _cm_err,
                    )
            else:
                # Fallback for scripts that only define build_* functions
                for _fn_name, _fn in exec_globals.items():
                    if _fn_name.startswith('build_') and callable(_fn):
                        try:
                            _fn()
                        except Exception as _build_err:
                            logger.warning("build_ fallback error for '%s': %s", material.name, _build_err)
                        _build_called = True
                        break

            new_materials = [m for m in bpy.data.materials if m not in existing_materials]
            new_node_groups = [ng for ng in bpy.data.node_groups if ng not in existing_node_groups]

            # If create_material ran but created nothing, try build_* as last resort.
            # Guard _build_called to avoid calling the same function twice.
            if not new_node_groups and not _build_called:
                for _fn_name, _fn in exec_globals.items():
                    if _fn_name.startswith('build_') and callable(_fn):
                        try:
                            _fn()
                        except Exception as _e:
                            logger.warning("build_ fallback failed for '%s': %s", material.name, _e)
                        new_node_groups = [ng for ng in bpy.data.node_groups if ng not in existing_node_groups]
                        if new_node_groups:
                            break

            if not new_materials and not new_node_groups:
                logger.error("No material or node groups created for '%s'", material.name)
                return None

            created_material = new_materials[0] if new_materials else None
            main_node_group = None
            material_name_clean = material.name.lower().replace(' ', '_')

            # Priority 0: use node_group_name if set by backend (exact match)
            if material.node_group_name and material.node_group_name != material.name:
                for ng in new_node_groups:
                    if ng.name == material.node_group_name:
                        main_node_group = ng
                        break

            if not main_node_group:
                for ng in new_node_groups:
                    ng_name_clean = ng.name.lower().replace(' ', '_')
                    if material_name_clean in ng_name_clean or ng_name_clean in material_name_clean:
                        main_node_group = ng
                        break

            if not main_node_group:
                for ng in new_node_groups:
                    try:
                        if hasattr(ng, 'interface') and hasattr(ng.interface, 'items_tree'):
                            output_names = [
                                item.name for item in ng.interface.items_tree
                                if hasattr(item, 'in_out') and item.in_out == 'OUTPUT'
                            ]
                            if any(n in ['Base Color', 'Metallic', 'Roughness', 'Normal',
                                         'Displacement', 'Emission'] for n in output_names):
                                main_node_group = ng
                                break
                        elif hasattr(ng, 'outputs'):
                            if any(o.name in ['Base Color', 'Metallic', 'Roughness', 'Normal',
                                              'Displacement', 'Emission'] for o in ng.outputs):
                                main_node_group = ng
                                break
                    except Exception as exc:
                        logger.warning("Error checking node group %s: %s", ng.name, exc)

            if not main_node_group:
                for ng in new_node_groups:
                    try:
                        if hasattr(ng, 'interface') and hasattr(ng.interface, 'items_tree'):
                            for item in ng.interface.items_tree:
                                if (hasattr(item, 'in_out') and item.in_out == 'OUTPUT'
                                        and hasattr(item, 'socket_type')
                                        and ('Color' in item.socket_type or 'RGBA' in item.socket_type)):
                                    main_node_group = ng
                                    break
                            if main_node_group:
                                break
                        elif hasattr(ng, 'outputs'):
                            if any(o.type == 'RGBA' for o in ng.outputs):
                                main_node_group = ng
                                break
                    except Exception as exc:
                        logger.warning("Error checking color outputs for %s: %s", ng.name, exc)

            if not main_node_group and new_node_groups:
                main_node_group = max(new_node_groups, key=lambda ng: len(ng.nodes))

            if not main_node_group:
                logger.error("No suitable node group found for '%s'", material.name)
                if created_material:
                    bpy.data.materials.remove(created_material)
                return None

            material.node_group_template = main_node_group
            material.node_group_name = main_node_group.name

            if created_material:
                bpy.data.materials.remove(created_material)

            return main_node_group

        except Exception:
            logger.exception("Failed to execute material script for '%s'", material.name)
            return None

    def load_materials_from_catalog(self, catalog_path: str, base_dir: str):
        """Load all materials from a local JSON catalog file."""
        if not os.path.exists(catalog_path):
            logger.warning("Materials catalog not found: %s", catalog_path)
            return

        try:
            with open(catalog_path, 'r', encoding='utf-8') as f:
                catalog_data = json.load(f)

            materials_data = catalog_data.get('materials', [])
            if not materials_data:
                return

            loaded_count = 0
            for mat_data in materials_data:
                try:
                    name = mat_data.get('name')
                    category = mat_data.get('category')
                    material_path = mat_data.get('material_path')
                    thumbnail_path = mat_data.get('thumbnail_path')

                    if not name or not category or not material_path:
                        continue

                    full_material_path = os.path.join(base_dir, material_path)
                    full_thumbnail_path = os.path.join(base_dir, thumbnail_path) if thumbnail_path else None

                    if not os.path.exists(full_material_path):
                        logger.warning("Material file not found: %s", full_material_path)
                        continue

                    material_id = (
                        mat_data.get('material_id')
                        or f"{category}_{name}".replace(' ', '_').replace('-', '_')
                    )
                    material = ProceduralMaterial(
                        material_id=material_id,
                        name=name,
                        category=category,
                        script_path=full_material_path,
                        thumbnail_path=full_thumbnail_path,
                        node_group_name=name,
                    )
                    self.register_material(material)
                    loaded_count += 1

                except Exception as exc:
                    logger.error("Failed to load material %s: %s", mat_data.get('name', 'unknown'), exc)

            self._loaded = True
            logger.info("Loaded %d materials from %s", loaded_count, os.path.basename(catalog_path))

        except Exception as exc:
            logger.error("Failed to load materials catalog %s: %s", catalog_path, exc)

    def clear(self):
        with self._lock:
            self._materials.clear()
            self._categories.clear()
            self._loaded = False


# ---------------------------------------------------------------------------
# Global registry instance
# ---------------------------------------------------------------------------

_registry = MaterialRegistry()


def get_registry() -> MaterialRegistry:
    return _registry

def register_material(material: ProceduralMaterial):
    _registry.register_material(material)

def get_material(material_id: str) -> Optional[ProceduralMaterial]:
    return _registry.get_material(material_id)

def get_all_materials() -> List[ProceduralMaterial]:
    return _registry.get_all_materials()

def get_categories() -> List[str]:
    return _registry.get_categories()

def get_materials_by_category(category: str) -> List[ProceduralMaterial]:
    return _registry.get_materials_by_category(category)

def is_custom_material(layer_type: str) -> bool:
    return _registry.is_custom_material(layer_type)

def get_node_group(material_id: str):
    return _registry.get_node_group(material_id)


def get_node_group_blocking(material_id: str):
    """Get or create the node group, fetching the script synchronously if needed.

    Used when the user explicitly clicks 'Add to Layer'. Blocks the main
    thread while downloading the script (typically <2 seconds on a fast
    connection). Returns the node group or None on failure.
    """
    # Fast path: already ready
    node_group = _registry.get_node_group(material_id)
    if node_group:
        return node_group

    material = _registry.get_material(material_id)
    if not material:
        return None

    # Script not cached — fetch it now (blocking)
    token = _get_auth_token()
    base_url = _get_base_url()
    if not token or not base_url:
        logger.warning("Cannot fetch script for '%s': not authenticated", material.name)
        return None

    logger.info("Fetching script for '%s'...", material.name)
    from .matgen_client import fetch_script_blocking as _client_fetch
    script = _client_fetch(material_id, token, base_url)
    if not script:
        logger.error("Failed to fetch script for '%s'", material.name)
        return None

    # Cache to disk and store on material object
    cache_dir = _get_cache_dir()
    cache_file = os.path.join(cache_dir, f"{material_id}.py")
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            f.write(script)
    except Exception as exc:
        logger.warning("Could not write script cache for %s: %s", material_id, exc)

    material.script = script
    return _registry._execute_material_script(material)


def unload_all_materials():
    _registry.clear()
    from .server_catalog import reset_server_catalog
    reset_server_catalog()


# ---------------------------------------------------------------------------
# Server catalog loader (non-blocking) — lifecycle in server_catalog.py
# ---------------------------------------------------------------------------

def load_server_catalog():
    """Start the backend catalog fetch (see ``server_catalog``)."""
    from .server_catalog import load_server_catalog as _load
    _load()


def _load_local_matgen():
    """Load the local AI-generated material catalog from the user data directory.

    User-generated materials are stored only on disk, not in the server DB, so
    they are loaded on their own regardless of the server catalog's state.
    """
    from .matgen_persistence import _get_matgen_paths
    _, catalog_path = _get_matgen_paths()
    base_dir = os.path.dirname(catalog_path)
    if os.path.exists(catalog_path):
        _registry.load_materials_from_catalog(catalog_path, base_dir)


def load_matgen_materials():
    _load_local_matgen()
