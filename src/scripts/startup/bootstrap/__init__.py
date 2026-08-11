# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar - Modular Blender Extension System

📁 LOCATION: src/scripts/startup/mixar/

New modular structure with automatic registration:
- bootstrap: Automatically registers all .py files with register/unregister functions
- modules/**/ui: Automatically registers all .py files with classes lists at the bottom

No __init__.py files needed in subdirectories!
"""

import importlib
import importlib.util
import os
from pathlib import Path
import sys
import logging
import time
import traceback

# Import logging configuration
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from mixar.config.logging_config import get_logger

# Get logger for this module
logger = get_logger(__name__)

# Track loaded modules for cleanup
_loaded_bootstrap_modules = []
_loaded_ui_modules = []

# --- Deferred UI loading state ---
_ui_files_queue = []
_ui_queue_index = 0
_ui_failed_modules = []
_ui_modules_path = None
_ui_loading_complete = False
# 4 ms per frame keeps main-thread blocking well below the 16 ms frame budget
# at 60 fps, eliminating the loading spinner while still loading ~415 UI
# modules in well under two seconds.  Configurable via config/mixar.json
# performance.ui_batch_budget_ms.
_UI_BATCH_BUDGET_MS = 4
_DISPLAY_KEYWORDS = ('panel', 'header', 'toolbar', 'menu')


def _get_mixar_path():
    """Get the path to the mixar directory"""
    # This file is in startup/bootstrap/__init__.py, we need to go to scripts/mixar
    return Path(__file__).parent.parent.parent / "mixar"


def _register_package(module_name, dir_path):
    """Register a directory as a synthetic Python package in sys.modules.

    Only creates a synthetic entry if:
    1. The directory does NOT have an __init__.py (real packages handle themselves).
    2. No sibling .py file with the same name exists (the file is the real module).
    """
    import types

    if module_name in sys.modules:
        return

    dir_path = Path(dir_path)
    init_file = dir_path / "__init__.py"
    if init_file.exists():
        # Real package — let Python's normal import machinery handle it
        logger.debug("Skipping %s (has __init__.py)", module_name)
        return

    # Check for a sibling .py file that would be shadowed by this directory
    sibling_py = dir_path.parent / (dir_path.name + ".py")
    if sibling_py.exists():
        logger.debug("Skipping %s (sibling .py file exists: %s)", module_name, sibling_py.name)
        return

    pkg = types.ModuleType(module_name)
    pkg.__path__ = [str(dir_path)]
    sys.modules[module_name] = pkg
    logger.debug("Created %s synthetic package", module_name)


def _discover_and_register_subpackages(base_path, base_module_name, max_depth=5):
    """Recursively discover and register all subdirectory packages under base_path.

    Sorts subdirectories alphabetically with 'properties' first to ensure
    property types are registered before UI elements that depend on them.
    Uses os.scandir for faster directory traversal (avoids extra stat calls).
    """
    if max_depth <= 0:
        return

    base_str = str(base_path)
    if not os.path.isdir(base_str):
        return

    _register_package(base_module_name, base_path)

    try:
        with os.scandir(base_str) as it:
            subdirs = sorted(
                [entry for entry in it
                 if entry.is_dir(follow_symlinks=False)
                 and not entry.name.startswith(('__', '.'))],
                key=lambda e: (0 if e.name == 'properties' else 1, e.name),
            )
    except OSError:
        return

    for entry in subdirs:
        child_name = f'{base_module_name}.{entry.name}'
        _discover_and_register_subpackages(
            Path(entry.path), child_name, max_depth - 1
        )


def _setup_mixar_packages():
    """Set up mixar parent packages in sys.modules for relative imports to work."""
    mixar_path = _get_mixar_path()
    modules_path = mixar_path / "modules"
    bootstrap_path = mixar_path / "bootstrap"
    config_path = mixar_path / "config"

    # Add mixar path to sys.path so imports work
    mixar_base = mixar_path.parent
    if str(mixar_base) not in sys.path:
        sys.path.insert(0, str(mixar_base))
        logger.debug("Added to sys.path: %s", mixar_base)

    # Register top-level mixar packages
    _register_package('mixar', mixar_path)
    _register_package('mixar.modules', modules_path)
    _register_package('mixar.bootstrap', bootstrap_path)
    _register_package('mixar.config', config_path)

    # Auto-discover and register all module subpackages
    if modules_path.exists():
        try:
            with os.scandir(modules_path) as it:
                module_dirs = sorted(
                    [entry for entry in it
                     if entry.is_dir(follow_symlinks=False)
                     and not entry.name.startswith(('__', '.'))],
                    key=lambda e: e.name,
                )
        except OSError:
            module_dirs = []
        for entry in module_dirs:
            _discover_and_register_subpackages(
                Path(entry.path),
                f'mixar.modules.{entry.name}',
            )


def _load_bootstrap_modules():
    """Automatically load and register all bootstrap modules with register functions"""
    bootstrap_path = _get_mixar_path() / "bootstrap"

    logger.debug("Looking for bootstrap modules in: %s", bootstrap_path)

    if not bootstrap_path.exists():
        logger.warning("Bootstrap directory not found at %s", bootstrap_path)
        return

    logger.debug("Loading bootstrap modules from %s", bootstrap_path)

    # Scan for Python files in bootstrap directory
    bootstrap_files = [f for f in bootstrap_path.glob("*.py") if not f.name.startswith("__")]

    if not bootstrap_files:
        logger.debug("No bootstrap modules found")
        return

    # Sort files to ensure consistent loading order
    bootstrap_files.sort(key=lambda x: x.name)

    logger.debug("Found %d bootstrap modules:", len(bootstrap_files))
    for py_file in bootstrap_files:
        logger.debug("  - %s", py_file.name)

    failed_modules = []  # (py_file, error) tuples for retry

    for py_file in bootstrap_files:
        module_name = py_file.stem
        logger.debug("Loading bootstrap module: %s", module_name)

        try:
            full_module_name = f"mixar.bootstrap.{module_name}"
            spec = importlib.util.spec_from_file_location(
                full_module_name,
                py_file
            )
            module = importlib.util.module_from_spec(spec)
            module.__mixar_module_name__ = module_name
            module.__mixar_file_path__ = str(py_file)
            # Register in sys.modules BEFORE executing so subsequent
            # `from mixar.bootstrap import <name>` calls (e.g. from
            # other bootstrap modules) resolve to this same instance.
            # Without this, Python re-imports the file from disk on
            # demand, creating a second module instance with its own
            # module-level state — every cross-module signal stored as
            # a module global (splash timestamp, connection singleton,
            # cache, etc.) silently diverges between the two copies.
            sys.modules[full_module_name] = module
            spec.loader.exec_module(module)

            if hasattr(module, 'register') and callable(module.register):
                logger.debug("Calling register() for bootstrap module: %s", module_name)
                module.register()
                _loaded_bootstrap_modules.append(module)
                logger.debug("Successfully registered bootstrap module: %s", module_name)
            else:
                logger.debug("Bootstrap module %s has no register function", module_name)

        except (ImportError, AttributeError) as e:
            failed_modules.append((py_file, e))
            logger.warning(
                "Bootstrap module %s deferred (dependency not yet loaded): %s",
                module_name, e,
            )
        except Exception as e:
            logger.error("✗ Failed to load bootstrap module %s: %s", module_name, e, exc_info=True)

    # Retry pass: modules that failed due to missing dependencies
    if failed_modules:
        logger.debug("Retrying %d deferred bootstrap module(s)...", len(failed_modules))
        for py_file, original_error in failed_modules:
            module_name = py_file.stem
            try:
                full_module_name = f"mixar.bootstrap.{module_name}"
                spec = importlib.util.spec_from_file_location(
                    full_module_name, py_file
                )
                module = importlib.util.module_from_spec(spec)
                module.__mixar_module_name__ = module_name
                module.__mixar_file_path__ = str(py_file)
                sys.modules[full_module_name] = module
                spec.loader.exec_module(module)

                if hasattr(module, 'register') and callable(module.register):
                    module.register()
                    _loaded_bootstrap_modules.append(module)
                    logger.debug("✓ Retry succeeded for bootstrap module: %s", module_name)
                else:
                    logger.debug("⚠ Bootstrap module %s has no register function", module_name)
            except Exception as retry_error:
                logger.error(
                    "✗ Bootstrap module %s failed on retry (possible circular dependency). "
                    "Original: %s | Retry: %s",
                    module_name, original_error, retry_error,
                )


def _discover_ui_files(modules_path):
    """Discover all UI module files using a single os.walk pass.

    Returns a sorted list of Path objects for .py files under **/ui/ dirs.
    Much faster than double recursive glob on Windows.
    """
    modules_str = str(modules_path)
    ui_files = []

    for root, dirs, files in os.walk(modules_str):
        # Prune hidden / dunder directories from traversal
        dirs[:] = [d for d in dirs if not d.startswith(('__', '.'))]

        # Only collect files inside a ui/ subtree
        rel_parts = os.path.relpath(root, modules_str).replace('\\', '/').split('/')
        if 'ui' not in rel_parts:
            continue

        for fname in files:
            if fname.endswith('.py') and not fname.startswith('__'):
                ui_files.append(Path(root, fname))

    # Sort order: properties (0) → operators/core (1) → panels/menus/headers (2)
    # Panels and menus draw operators immediately when registered, so all
    # operators must be loaded before any panel/menu/header/toolbar.
    def sort_key(x):
        parts_lower = {p.lower() for p in x.parts}
        stem_lower = x.stem.lower()

        if 'properties' in parts_lower:
            priority = 0
        elif any(kw in stem_lower for kw in _DISPLAY_KEYWORDS) \
                or parts_lower & {'panels', 'menus'}:
            priority = 2
        else:
            priority = 1

        return (priority, len(x.parts), str(x))

    ui_files.sort(key=sort_key)
    return ui_files


def _register_single_ui_module(ui_file, modules_path):
    """Load and register a single UI module file.

    exec_module and register() are intentionally kept together in one call so
    that class objects created during exec are the same objects passed to
    bpy.utils.register_class — avoiding the class-identity mismatch that
    occurs when the two phases are separated across threads.
    """
    import bpy
    relative_path = ui_file.relative_to(modules_path)
    module_parts = list(relative_path.parts[:-1]) + [relative_path.stem]
    module_name = ".".join(module_parts)

    try:
        full_module_name = f"mixar.modules.{module_name}"

        module = sys.modules.get(full_module_name)
        if module is not None:
            # Already imported — either synchronously by a mixar.bootstrap
            # module (agent_bubble, workflow, ...) or as a dependency of a
            # previously loaded UI file (e.g. moodboard's ui/operators/
            # __init__.py imports every sibling ops file). Re-executing the
            # file would mint NEW class objects with the same bl_idnames;
            # register_class() then replaces the originals by unregistering
            # them, which frees their wmOperatorTypes while already-drawn
            # buttons still point at them — hovering such a button segfaults
            # in tooltip creation (but->optype->idname use-after-free).
            # Reuse the live module and only register what's missing.
            module.__mixar_module_name__ = module_name
            module.__mixar_file_path__ = str(ui_file)
            existing_classes = getattr(module, 'classes', None)
            if isinstance(existing_classes, (list, tuple)) and existing_classes and all(
                getattr(cls, 'is_registered', False) for cls in existing_classes
            ):
                logger.debug("UI module already registered, skipping: %s", module_name)
                return
        else:
            spec = importlib.util.spec_from_file_location(full_module_name, ui_file)
            module = importlib.util.module_from_spec(spec)

            module.__mixar_module_name__ = module_name
            module.__mixar_file_path__ = str(ui_file)

            # Add to sys.modules BEFORE executing so relative imports work
            sys.modules[full_module_name] = module

            spec.loader.exec_module(module)

        if hasattr(module, 'register') and callable(module.register):
            module.register()
            _loaded_ui_modules.append(module)
            logger.debug("✓ Registered UI module: %s", module_name)
        elif hasattr(module, 'classes') and isinstance(module.classes, (list, tuple)):
            registered_count = 0
            for cls in module.classes:
                if getattr(cls, 'is_registered', False):
                    continue
                try:
                    bpy.utils.register_class(cls)
                    registered_count += 1
                except ValueError as e:
                    if "already registered" not in str(e):
                        logger.warning("✗ Failed to register class %s: %s", cls.__name__, e)
                except Exception as e:
                    logger.error("✗ Error registering class %s: %s", cls.__name__, e)

            if registered_count > 0:
                _loaded_ui_modules.append(module)
                logger.debug("✓ Registered %d/%d classes from: %s",
                            registered_count, len(module.classes), module_name)
        else:
            logger.debug("⚠ UI module %s has no register() function or classes list", module_name)

    except (ImportError, AttributeError) as e:
        _ui_failed_modules.append((ui_file, e))
        logger.warning("UI module %s deferred: %s", module_name, e)
    except Exception as e:
        logger.error("✗ Failed to load UI module %s: %s", module_name, e, exc_info=True)


def _retry_failed_ui_modules():
    """Retry loading UI modules that failed due to missing dependencies.

    Two-pass design (intentional):
      Pass 1 — snapshot _ui_failed_modules into retry_list, then clear it so
               _register_single_ui_module can freely re-append new failures.
      Pass 2 — iterate retry_list and call _register_single_ui_module; any
               modules that still fail are re-appended to the (now empty)
               _ui_failed_modules, then logged and cleared below.
    This avoids modifying the list we're iterating over.
    """
    if not _ui_failed_modules:
        return

    logger.debug("Retrying %d deferred UI module(s)...", len(_ui_failed_modules))
    retry_list = list(_ui_failed_modules)
    _ui_failed_modules.clear()  # Pass 1: clear so re-failures can be collected fresh

    for ui_file, _ in retry_list:  # Pass 2: attempt each deferred module once more
        _register_single_ui_module(ui_file, _ui_modules_path)

    # Log any modules that still failed after retry
    for ui_file, error in _ui_failed_modules:
        rel = ui_file.relative_to(_ui_modules_path)
        logger.error("UI module %s failed on retry: %s", rel, error)
    _ui_failed_modules.clear()


def _load_ui_batch_tick():
    """Timer callback: load UI modules in time-budgeted batches.

    Processes modules for up to _UI_BATCH_BUDGET_MS per frame (default 4 ms),
    then yields control back to Blender so the event loop stays responsive.
    At 60 fps the main thread is occupied for at most 25 % of each frame —
    well below the threshold that produces a visible loading spinner.

    Returns 0.0 to be called again next frame, or None to stop.
    An unhandled exception would cause Blender to silently unregister the timer,
    leaving UI loading permanently incomplete — the broad try/except prevents that.
    """
    global _ui_queue_index, _ui_loading_complete

    try:
        budget = _UI_BATCH_BUDGET_MS / 1000.0
        start = time.perf_counter()
        total = len(_ui_files_queue)

        while _ui_queue_index < total and (time.perf_counter() - start) < budget:
            ui_file = _ui_files_queue[_ui_queue_index]
            _ui_queue_index += 1
            _register_single_ui_module(ui_file, _ui_modules_path)

        if _ui_queue_index < total:
            # More files to process — schedule next frame
            return 0.0

        # All files processed — run retry pass and mark complete
        _retry_failed_ui_modules()
        _ui_loading_complete = True
        logger.debug("Deferred UI loading complete (%d modules registered)", len(_loaded_ui_modules))
        return None

    except Exception as e:
        logger.error("UI batch tick failed — deferred loading may be incomplete: %s", e, exc_info=True)
        return None  # Stop the timer; partial loading is better than a crash loop


def _initialize_theme_defaults():
    """Initialize default theme colors for Mixie Chat"""
    import bpy
    try:
        theme = bpy.context.preferences.themes[0]
        theme.space_mixie_chat.chat_bubble_hover = (0.3, 0.85, 0.95, 0.95)
        # Past-chats overlay row hover. Seeded every launch (like
        # chat_bubble_hover) so prefs saved before the field existed —
        # which load it as zero — still get a sensible value. Tune the
        # look here or via theme.space_mixie_chat.chat_history_row_hover.
        theme.space_mixie_chat.chat_history_row_hover = (1.0, 1.0, 1.0, 0.07)
        logger.debug("Initialized mixie chat theme colors")
    except Exception as e:
        logger.debug("Could not initialize theme defaults: %s", e)


def register():
    """Register all Mixar modules automatically.

    Bootstrap modules (property groups, core systems) are loaded synchronously
    since they're few and needed immediately. UI modules (~415 files) are loaded
    in deferred batches via bpy.app.timers, spending at most _UI_BATCH_BUDGET_MS
    milliseconds per frame so Blender's event loop stays responsive throughout.
    """
    global _ui_modules_path, _ui_queue_index, _ui_loading_complete, _UI_BATCH_BUDGET_MS
    logger.debug("Registering Mixar modular system")

    try:
        import bpy
        import json as _json

        # Read tunable parameters from config (per CLAUDE.md: env vars go in mixar.json).
        # Path is relative to __file__ (startup/bootstrap/__init__.py); 4 parents reaches
        # the directory that contains both scripts/ and config/ in the Blender install.
        # bpy.utils.resource_path('LOCAL') is the user data dir and would never find this file.
        try:
            _cfg_path = Path(__file__).parent.parent.parent.parent / 'config' / 'mixar.json'
            with open(_cfg_path, 'r') as _f:
                _cfg = _json.load(_f)
            _UI_BATCH_BUDGET_MS = _cfg.get('performance', {}).get('ui_batch_budget_ms', 4)
        except Exception:
            pass  # Keep module-level default

        # 0. Set up mixar packages in sys.modules first (required for relative imports)
        _setup_mixar_packages()

        # 1. Load and register bootstrap modules first (synchronous, only ~5 files)
        _load_bootstrap_modules()

        # 1b. Register versioning handlers (must be before UI so migrations run early)
        try:
            from mixar.modules.common.versioning.handlers import register as register_versioning
            register_versioning()
        except Exception as e:
            logger.warning("Failed to register versioning handlers: %s", e)

        # 2. Discover UI files (fast os.walk, no loading yet)
        _ui_modules_path = _get_mixar_path() / "modules"

        if not _ui_modules_path.exists():
            logger.warning("Modules directory not found at %s", _ui_modules_path)

        ui_files = _discover_ui_files(_ui_modules_path)

        if ui_files:
            _ui_files_queue.clear()  # Prevent double-registration on addon reload
            _ui_files_queue.extend(ui_files)
            _ui_queue_index = 0
            _ui_loading_complete = False

            logger.debug(
                "Scheduling deferred loading of %d UI modules (%d ms/frame budget)",
                len(ui_files), _UI_BATCH_BUDGET_MS,
            )
            bpy.app.timers.register(
                _load_ui_batch_tick, first_interval=0.0, persistent=True
            )
        else:
            _ui_loading_complete = True
            logger.debug("No UI modules found")

        # 3. Initialize theme defaults
        _initialize_theme_defaults()

        # 4. Start API background infrastructure
        try:
            from mixar.modules.common.api import start_executor, start_api_processor
            start_executor()
            start_api_processor()
            logger.debug("API background infrastructure started")
        except Exception as e:
            logger.warning("Failed to start API infrastructure: %s", e)

        logger.debug("Mixar registration started (UI loading deferred)")

    except Exception as e:
        logger.error("Failed to register Mixar system: %s", e, exc_info=True)


def unregister():
    """Unregister all Mixar modules"""
    global _ui_loading_complete, _ui_queue_index
    logger.debug("Unregistering Mixar modular system")

    try:
        # 0a. Cancel deferred UI loading timer if still running
        if not _ui_loading_complete:
            try:
                import bpy
                if bpy.app.timers.is_registered(_load_ui_batch_tick):
                    bpy.app.timers.unregister(_load_ui_batch_tick)
                    logger.debug("Cancelled deferred UI module loading")
            except Exception:
                pass

        # Always clean up deferred state so register() starts fresh on the next call
        _ui_files_queue.clear()
        _ui_failed_modules.clear()
        _ui_queue_index = 0
        _ui_loading_complete = False

        # 0b. Unregister versioning handlers
        try:
            from mixar.modules.common.versioning.handlers import unregister as unregister_versioning
            unregister_versioning()
        except Exception as e:
            logger.warning("Failed to unregister versioning handlers: %s", e)

        # 0c. Stop API background infrastructure first
        try:
            from mixar.modules.common.api import stop_api_processor, stop_executor
            stop_api_processor()
            stop_executor()
            logger.debug("API background infrastructure stopped")
        except Exception as e:
            logger.warning("Failed to stop API infrastructure: %s", e)

        # Unregister UI modules first (in reverse order)
        if _loaded_ui_modules:
            logger.debug("Unregistering %d UI modules...", len(_loaded_ui_modules))
            for module in reversed(_loaded_ui_modules):
                module_name = getattr(module, '__mixar_module_name__', getattr(module, '__name__', 'unknown'))
                if hasattr(module, 'unregister') and callable(module.unregister):
                    try:
                        logger.debug("Calling unregister() for UI module: %s", module_name)
                        module.unregister()
                        logger.debug("✓ Successfully unregistered UI module: %s", module_name)
                    except Exception as e:
                        logger.error("✗ Error unregistering UI module %s: %s", module_name, e)
                elif hasattr(module, 'classes') and isinstance(module.classes, (list, tuple)):
                    import bpy
                    unregistered_count = 0
                    logger.debug("Unregistering %d classes from module %s:", len(module.classes), module_name)
                    try:
                        for cls in reversed(module.classes):
                            try:
                                logger.debug("  Unregistering class: %s", cls.__name__)
                                if hasattr(cls, 'is_registered') and cls.is_registered:
                                    bpy.utils.unregister_class(cls)
                                    unregistered_count += 1
                                    logger.debug("  ✓ Successfully unregistered: %s", cls.__name__)
                                else:
                                    logger.debug("  ⚠ Class %s not registered or no is_registered attr", cls.__name__)
                            except Exception as e:
                                logger.warning("  ✗ Failed to unregister class %s: %s", cls.__name__, e)

                        if unregistered_count > 0:
                            logger.debug("✓ Successfully unregistered %d/%d classes from UI module: %s",
                                        unregistered_count, len(module.classes), module_name)
                        else:
                            logger.debug("⚠ No classes to unregister in UI module: %s", module_name)
                    except Exception as e:
                        logger.error("✗ Error unregistering UI module %s: %s", module_name, e)
                else:
                    logger.debug("⚠ UI module %s has no classes list or unregister function", module_name)

        # Unregister bootstrap modules (in reverse order)
        if _loaded_bootstrap_modules:
            logger.debug("Unregistering %d bootstrap modules...", len(_loaded_bootstrap_modules))
            for module in reversed(_loaded_bootstrap_modules):
                module_name = getattr(module, '__mixar_module_name__', getattr(module, '__name__', 'unknown'))
                if hasattr(module, 'unregister') and callable(module.unregister):
                    try:
                        logger.debug("Calling unregister() for bootstrap module: %s", module_name)
                        module.unregister()
                        logger.debug("✓ Successfully unregistered bootstrap module: %s", module_name)
                    except Exception as e:
                        logger.error("✗ Error unregistering bootstrap module %s: %s", module_name, e)
                else:
                    logger.debug("⚠ Bootstrap module %s has no unregister function", module_name)

        # Clear module lists
        _loaded_bootstrap_modules.clear()
        _loaded_ui_modules.clear()

        logger.debug("Mixar modular system unregistration completed")

    except Exception as e:
        logger.error("Error during Mixar system unregistration: %s", e)


# Export classes for Blender registration system
classes = [
    # Will be populated by modules as they register
]
