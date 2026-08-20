# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Static and live-Blender checks for add-on projects."""

import importlib
import sys
import traceback
from pathlib import Path

from .indexer import read_source
from .paths import iter_project_files


def run_static_checks(root: Path) -> dict:
    results = []
    passed = True
    for relative, path in iter_project_files(root):
        if path.suffix.lower() != ".py":
            continue
        try:
            source, _ = read_source(path, limit=1_000_000)
            compile(source, relative, "exec")
            results.append({"path": relative, "check": "python_compile", "success": True})
        except Exception as exc:
            passed = False
            line = getattr(exc, "lineno", None)
            results.append({
                "path": relative,
                "check": "python_compile",
                "success": False,
                "line": line,
                "message": getattr(exc, "msg", None) or str(exc),
            })
    return {"success": passed, "checks": results, "summary": f"{sum(r['success'] for r in results)}/{len(results)} Python files compiled"}


def run_blender_reload(root: Path, entrypoint: str) -> dict:
    """Import and exercise register/unregister on Blender's main thread."""
    if not entrypoint:
        return {
            "success": False,
            "check": "blender_reload",
            "message": "Set an entrypoint module in .mixar/addon-project.json first",
        }
    root = root.resolve(strict=True)
    top_level = entrypoint.split(".", 1)[0]
    import_root = (
        root.parent
        if top_level == root.name and (root / "__init__.py").is_file()
        else root
    )
    original_path = list(sys.path)
    old_module = sys.modules.get(entrypoint)
    old_modules = {
        name: loaded for name, loaded in sys.modules.items()
        if name == entrypoint or name.startswith(entrypoint + ".")
    }
    was_enabled = bool(getattr(old_module, "__addon_enabled__", False))
    was_persistent = bool(getattr(old_module, "__addon_persistent__", False))
    module = None
    test_registered = False
    try:
        import addon_utils

        if str(import_root) not in sys.path:
            sys.path.insert(0, str(import_root))
        if was_enabled:
            addon_utils.disable(entrypoint, default_set=False)
        for name in list(sys.modules):
            if name == entrypoint or name.startswith(entrypoint + "."):
                del sys.modules[name]
        importlib.invalidate_caches()
        if was_enabled:
            module = addon_utils.enable(
                entrypoint,
                default_set=False,
                persistent=was_persistent,
            )
            if module is None:
                raise RuntimeError("Blender could not re-enable the add-on")
        else:
            module = importlib.import_module(entrypoint)
        register = getattr(module, "register", None)
        unregister = getattr(module, "unregister", None)
        if not callable(register) or not callable(unregister):
            raise RuntimeError("Entrypoint must define callable register() and unregister()")
        if not was_enabled:
            test_registered = True
            register()
            unregister()
            test_registered = False
        return {
            "success": True,
            "check": "blender_reload",
            "message": "Add-on imported and registration lifecycle passed",
            "left_enabled": was_enabled,
        }
    except Exception as exc:
        if module is not None and (test_registered or was_enabled):
            try:
                module.unregister()
            except Exception:
                pass
        if was_enabled and old_module is not None:
            try:
                for name in list(sys.modules):
                    if name == entrypoint or name.startswith(entrypoint + "."):
                        del sys.modules[name]
                sys.modules.update(old_modules)
                old_module.register()
                old_module.__addon_enabled__ = True
                old_module.__addon_persistent__ = was_persistent
            except Exception:
                pass
        return {
            "success": False,
            "check": "blender_reload",
            "message": str(exc),
            "traceback": traceback.format_exc(limit=8),
        }
    finally:
        sys.path[:] = original_path
