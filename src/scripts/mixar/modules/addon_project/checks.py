# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Static and live-Blender checks for add-on projects."""

import contextlib
import importlib
import io
import os
import pkgutil
import sys
import traceback
from pathlib import Path

from .indexer import read_source
from .installer import install_addon
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


def run_scoped_checks(scoped_roots) -> dict:
    """Compile each (root, path_prefix) pair and merge into one result.

    Workspace commits scope their static pass exactly like ``run_checks``:
    one add-on's syntax error must not block work on another. Each root's
    reported paths are prefixed so they stay project-relative and
    unambiguous (``pkg/module.py``), and the summaries concatenate.
    """
    checks = []
    passed = True
    parts = []
    for scope_root, prefix in scoped_roots:
        result = run_static_checks(scope_root)
        passed = passed and result["success"]
        parts.append(result["summary"])
        for item in result.get("checks", []):
            if prefix:
                item["path"] = f"{prefix}{item['path']}"
            checks.append(item)
    return {"success": passed, "checks": checks, "summary": "; ".join(parts)}


# What the agent sees of a failure: the frames INSIDE the project (relative
# path, line, function, source line) and the tail of what the add-on printed.
# Frames outside the project are Blender's or this harness's and are dropped —
# they carry local install paths and never name the line to fix.
MAX_FRAMES = 20
CONSOLE_TAIL = 4000
# Owners whose runtime properties an add-on typically registers onto.
_PROP_OWNERS = ("Scene", "Object", "WindowManager", "Mesh", "Material", "Collection", "Image")


def project_frames(exc_or_tb, root: Path) -> list:
    """Traceback frames under ``root``, project-relative; nothing else.
    Takes an exception or a traceback object."""
    root = Path(root).resolve()
    tb = exc_or_tb if not isinstance(exc_or_tb, BaseException) else exc_or_tb.__traceback__
    frames = []
    for frame in traceback.extract_tb(tb):
        try:
            relative = Path(frame.filename).resolve().relative_to(root)
        except (OSError, ValueError):
            continue
        frames.append({
            "path": relative.as_posix(),
            "line": frame.lineno,
            "function": frame.name,
            "code": (frame.line or "")[:200],
        })
    return frames[-MAX_FRAMES:]


def import_submodules(module) -> list:
    """Import every submodule of the package — a module ``__init__`` never
    wires is otherwise never compiled past syntax. ``tests`` is run_tests' job."""
    path = getattr(module, "__path__", None)
    if not path:
        return []
    imported = []
    for info in pkgutil.walk_packages(path, prefix=module.__name__ + "."):
        if info.name.split(".")[-1] == "tests" or ".tests." in info.name:
            continue
        importlib.import_module(info.name)
        imported.append(info.name)
    return imported


def package_classes(entrypoint: str) -> list:
    """Classes defined by the package's loaded modules."""
    found = []
    for name, module in list(sys.modules.items()):
        if name != entrypoint and not name.startswith(entrypoint + "."):
            continue
        for value in list(vars(module).values()):
            if isinstance(value, type) and str(getattr(value, "__module__", "")).startswith(entrypoint):
                found.append(value)
    return found


def registration_snapshot(entrypoint: str) -> dict:
    """What Blender holds that an add-on can leak: keymap items, app handlers
    from the package, runtime RNA properties on the usual owners. Each probe is
    best-effort — an API that is not there (background mode, no window) counts
    as empty, never as a failure."""
    snap = {"keymap": set(), "handler": set(), "property": set()}
    try:
        import bpy
    except Exception:
        return snap
    try:
        kc = bpy.context.window_manager.keyconfigs.addon
        for km in (kc.keymaps if kc else ()):
            for kmi in km.keymap_items:
                snap["keymap"].add(f"{km.name}: {kmi.idname} {kmi.type} {kmi.value}")
    except Exception:
        pass
    try:
        for attr in dir(bpy.app.handlers):
            seq = getattr(bpy.app.handlers, attr, None)
            if isinstance(seq, list):
                for fn in seq:
                    if str(getattr(fn, "__module__", "")).startswith(entrypoint):
                        snap["handler"].add(f"{attr}: {getattr(fn, '__qualname__', repr(fn))}")
    except Exception:
        pass
    for owner in _PROP_OWNERS:
        try:
            for prop in getattr(bpy.types, owner).bl_rna.properties:
                if getattr(prop, "is_runtime", False):
                    snap["property"].add(f"{owner}.{prop.identifier}")
        except Exception:
            pass
    return snap


def registration_leaks(entrypoint: str, before: dict, after: dict) -> list:
    """What ``unregister()`` left behind: classes still registered, and every
    keymap item / handler / property present after that was not before."""
    leaks = []
    try:
        import bpy
        for cls in package_classes(entrypoint):
            if getattr(bpy.types, cls.__name__, None) is cls:
                leaks.append({"kind": "class", "name": cls.__name__})
    except Exception:
        pass
    for kind in ("keymap", "handler", "property"):
        for name in sorted(after.get(kind, set()) - before.get(kind, set())):
            leaks.append({"kind": kind, "name": name})
    return leaks


class RegistrationLeak(RuntimeError):
    def __init__(self, leaks: list):
        names = ", ".join(f"{item['kind']} {item['name']}" for item in leaks)
        super().__init__(f"unregister() left {len(leaks)} registration(s) behind: {names}")
        self.leaks = leaks


def run_blender_reload(
    root: Path,
    entrypoint: str,
    *,
    allow_root_package=True,
    deliberately_disabled=False,
    go_live=True,
) -> dict:
    """Import and exercise register/unregister on Blender's main thread.

    Every run is the same dry run: purge the package, import it and every
    submodule, register / unregister TWICE with a registration audit around
    it (a leak shows on the second cycle as "already registered", or here as
    a named leftover), then re-enable it if it was enabled, or install it if
    it was not. Everything the add-on prints is returned as ``console``; a
    failure names its project frames.

    ``deliberately_disabled`` comes from the machine-local disable stamps
    (service layer): only an EXPLICIT set_enabled(False)/uninstall skips the
    auto-enable — a bare "link exists but not enabled" state also matches
    stale links and enables that never persisted to prefs, which must
    re-enable.

    ``go_live=False`` is the verified commit's proof step: the dry run and
    the re-enable of an already enabled add-on happen as always, but a
    not-yet-enabled add-on is left imported and unregistered, never
    installed — the commit installs it only once its tests have passed too.
    """
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
    console = io.StringIO()
    try:
        with contextlib.redirect_stdout(console), contextlib.redirect_stderr(console):
            import addon_utils

            if str(import_root) not in sys.path:
                sys.path.insert(0, str(import_root))
            if was_enabled:
                addon_utils.disable(entrypoint, default_set=False)
            for name in list(sys.modules):
                if name == entrypoint or name.startswith(entrypoint + "."):
                    del sys.modules[name]
            importlib.invalidate_caches()
            module = importlib.import_module(entrypoint)
            submodules = import_submodules(module)
            register = getattr(module, "register", None)
            unregister = getattr(module, "unregister", None)
            if not callable(register) or not callable(unregister):
                raise RuntimeError("Entrypoint must define callable register() and unregister()")
            before = registration_snapshot(entrypoint)
            for _cycle in range(2):
                test_registered = True
                register()
                unregister()
                test_registered = False
            leaks = registration_leaks(entrypoint, before, registration_snapshot(entrypoint))
            if leaks:
                raise RegistrationLeak(leaks)
            if was_enabled:
                # addon_utils.enable reloads a module whose mtime it does not
                # know; stamp the one we just imported so it registers as is.
                module_file = getattr(module, "__file__", None)
                if module_file:
                    module.__time__ = os.path.getmtime(module_file)
                errors = []
                module = addon_utils.enable(
                    entrypoint,
                    default_set=False,
                    persistent=was_persistent,
                    handle_error=errors.append,
                )
                if module is None:
                    raise (errors[0] if errors else RuntimeError("Blender could not re-enable the add-on"))
        result = {
            "success": True,
            "check": "blender_reload",
            "message": "Add-on imported, every module loaded, registration cycled twice without leaks",
            "left_enabled": was_enabled,
            "submodules": len(submodules),
        }
        if not was_enabled and go_live:
            # A passing, not-yet-enabled add-on gets installed so it is live
            # now and survives restarts. Install failures (dotted entrypoint,
            # target collision, no symlink privilege) never fail the checks
            # themselves — the structured "install" result explains why the
            # add-on is not live yet. Exception: an entrypoint carrying a
            # deliberate-disable stamp must not be forced back on.
            if deliberately_disabled:
                install = {
                    "success": False,
                    "installed": False,
                    "reason": "disabled_by_user",
                    "message": (
                        "Add-on is installed but disabled; enable it to "
                        "make it live"
                    ),
                }
            else:
                with contextlib.redirect_stdout(console), contextlib.redirect_stderr(console):
                    install = install_addon(
                        root, entrypoint, allow_root_package=allow_root_package
                    )
            result["install"] = install
            result["installed"] = bool(install.get("success"))
            if install.get("success"):
                result["left_enabled"] = True
                result["message"] = "Add-on installed and enabled"
        _with_console(result, console)
        return result
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
        result = {
            "success": False,
            "check": "blender_reload",
            "message": f"{type(exc).__name__}: {exc}",
            "frames": project_frames(exc, root),
        }
        if isinstance(exc, RegistrationLeak):
            result["leaks"] = exc.leaks
        _with_console(result, console)
        return result
    finally:
        sys.path[:] = original_path


def _with_console(result: dict, console: io.StringIO) -> None:
    text = console.getvalue()
    if text.strip():
        result["console"] = text[-CONSOLE_TAIL:]
