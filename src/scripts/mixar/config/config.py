# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar Configuration Utilities

Provides centralized configuration loading for all Mixar modules.

Two files back the configuration and they must never be confused:

* The **bundled** ``<install>/5.0/config/mixar.json`` is generated at build
  time (``scripts/generate_config.py``): backend URLs, environment, update
  channel. In an installed build it is READ-ONLY input -- on Windows the
  MSI puts it under ``C:\\Program Files`` where a standard user has no write
  access, and on macOS the ``.app`` bundle is replaced wholesale by updates.
* The **user overlay** ``<user config>/mixar/mixar.json`` holds every key a
  running app persists (``ui_mode``, ``share_usage_data``, the fallback
  ``device_id``). It contains ONLY keys written through :func:`add_config`,
  so a stale copy of a bundled key can never shadow a newer build's value.

Reads see the overlay merged over the bundled defaults; writes go to the
overlay alone. Writing into the install directory used to hang the whole
app on installed Windows builds: CPython's ``tempfile.mkstemp`` treats a
``PermissionError`` on Windows as a name collision whenever
``os.access(dir, W_OK)`` says the directory is writable -- and on Windows
``os.access`` only checks the read-only attribute, never the ACL -- so it
retried ``TMP_MAX`` (2**31) times on the main thread. That was the
"Start with Zen Mode" / "Engine Mode" hang on the splash screen.
"""

import os
import json
import bpy

from .logging_config import get_logger

logger = get_logger(__name__)


UI_MODE_AI = "ai"
UI_MODE_PRO = "pro"
_UI_MODES = (UI_MODE_AI, UI_MODE_PRO)

# Sub-folder of Blender's per-user CONFIG resource that holds the overlay.
USER_CONFIG_SUBDIR = 'mixar'
USER_CONFIG_FILENAME = 'mixar.json'

# Exclusive-create attempts before a temp-file name collision is an error.
# Bounded on purpose (see ``_create_temp_file``).
_TMP_CREATE_ATTEMPTS = 8


def get_config_path():
    """Path of the bundled, build-generated config (read-only in installs)."""
    return os.path.join(bpy.utils.resource_path('LOCAL'), 'config', 'mixar.json')


def get_user_config_path():
    """Path of the per-user overlay that :func:`add_config` writes.

    Lives under Blender's user CONFIG resource (``%APPDATA%\\Mixar\\...`` on
    Windows, ``~/Library/Application Support/Mixar/...`` on macOS), which
    is writable without elevation and survives reinstalls and updates.

    Raises ``OSError`` when Blender cannot provide (or create) the folder,
    so callers fail closed instead of writing somewhere unexpected.
    """
    base = bpy.utils.user_resource('CONFIG', path=USER_CONFIG_SUBDIR, create=True)
    if not isinstance(base, str) or not base:
        raise OSError("user config directory unavailable")
    return os.path.join(base, USER_CONFIG_FILENAME)


def _backup_corrupt_config(config_path, error):
    """Move a corrupt config file aside (mixar.json.corrupt-<ts>) so reads can
    rebuild from defaults and the next write cannot erase its contents."""
    import time
    stamp = time.strftime('%Y%m%d-%H%M%S')
    backup_path = '%s.corrupt-%s' % (config_path, stamp)
    counter = 1
    while os.path.exists(backup_path):
        # Same-second collision: never clobber an earlier backup.
        backup_path = '%s.corrupt-%s.%d' % (config_path, stamp, counter)
        counter += 1
    try:
        os.replace(config_path, backup_path)
        logger.error("Corrupt config %s (%s); backed up to %s, rebuilding "
                     "from defaults", config_path, error, backup_path)
    except OSError as exc:
        logger.error("Corrupt config %s (%s); could not back up to %s: %s",
                     config_path, error, backup_path, exc)


def _read_config_file(config_path, warn_missing=False):
    """Parse the config file. Returns a dict; {} when missing or corrupt.

    A corrupt file is backed up and treated as missing so reads rebuild
    from defaults instead of failing, and so the next write cannot erase
    the keys that could not be parsed."""
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
    except FileNotFoundError:
        if warn_missing:
            logger.warning("Config file not found at: %s", config_path)
        return {}
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        _backup_corrupt_config(config_path, e)
        return {}
    except Exception as e:
        logger.error("Error loading config: %s", e)
        return {}
    if not isinstance(config, dict):
        # Valid JSON but not an object -- unusable as config, same treatment.
        _backup_corrupt_config(config_path, "not a JSON object")
        return {}
    return config


def _read_user_config():
    """The overlay as currently on disk; {} when unavailable."""
    try:
        return _read_config_file(get_user_config_path())
    except Exception as e:
        logger.debug("User config unavailable: %s", e)
        return {}


def load_mixar_config():
    """Load Mixar configuration: bundled defaults with the user overlay on top."""
    try:
        bundled = _read_config_file(get_config_path(), warn_missing=True)
    except Exception as e:
        logger.error("Error loading config: %s", e)
        bundled = {}
    return {**bundled, **_read_user_config()}


# Global config instance: the merged view (bundled defaults + user overlay).
_config = None
# Keys persisted through add_config() during this process. Only these (plus
# whatever the overlay already holds on disk) are ever written -- never the
# merged view, or bundled keys would leak into the overlay and shadow the
# next build's values.
_user_overrides = {}


def get_config():
    """Get the global configuration, loading it if necessary"""
    global _config
    if _config is None:
        _config = load_mixar_config()
    return _config


def add_config(key, value):
    """Set a key in the live configuration and persist it to the user overlay.

    Never writes the bundled file. Returns False on any write failure; the
    in-memory value is kept either way so the running session is consistent.
    """
    global _config
    if _config is None:
        _config = load_mixar_config()
    _config[key] = value
    _user_overrides[key] = value

    # Merge over what the overlay currently holds on disk so keys written by
    # another session (or an earlier process) are not erased. In-memory
    # values win for keys present in both.
    try:
        user_path = get_user_config_path()
        merged = {**_read_config_file(user_path), **_user_overrides}
        _write_config_file(user_path, merged)
        return True
    except Exception as e:
        logger.error("Error saving config: %s", e)
        return False


def _create_temp_file(directory, prefix, suffix):
    """Exclusive-create a fresh temp file in ``directory``; returns (fd, path).

    Deliberately NOT ``tempfile.mkstemp``: on Windows, mkstemp mistakes a
    ``PermissionError`` for a name collision whenever ``os.access(dir, W_OK)``
    is true -- and ``os.access`` there ignores ACLs -- so an unwritable
    directory makes it retry ``TMP_MAX`` (2**31) times. Here a permission
    failure propagates on the first attempt and only a genuine collision
    retries, a bounded number of times.
    """
    flags = (os.O_RDWR | os.O_CREAT | os.O_EXCL
             | getattr(os, 'O_NOINHERIT', 0) | getattr(os, 'O_BINARY', 0))
    for _ in range(_TMP_CREATE_ATTEMPTS):
        path = os.path.join(directory, '%s%s%s' % (prefix, os.urandom(4).hex(), suffix))
        try:
            return os.open(path, flags, 0o600), path
        except FileExistsError:
            continue
    raise FileExistsError(
        "could not find a free temp file name in %r after %d attempts"
        % (directory, _TMP_CREATE_ATTEMPTS))


def _write_config_file(config_path, config):
    """Atomically write the config file (temp file + os.replace) so a crash
    mid-write cannot leave a corrupt mixar.json behind."""
    fd, tmp_path = _create_temp_file(
        os.path.dirname(config_path), prefix='.mixar.json.', suffix='.tmp'
    )
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(config, f, indent=2)
        os.replace(tmp_path, config_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def get_environment():
    """Get the current environment from config"""
    config = get_config()
    return config.get('environment', 'Prod')


def get_server_url():
    """Get the API server URL (resolved at build time via env vars)."""
    config = get_config()
    return config.get('backend_url', 'https://api.mixar.app')


def get_dev_bypass_credentials() -> tuple:
    """Return (username, password) for dev bypass login, or ('', '') if disabled.

    Gated on a build-time constant in ``_build_env.py``, not on the mutable
    ``mixar.json``. The ``_build_env`` module is auto-generated by
    ``scripts/unix/build.sh`` / ``scripts/windows/build.bat`` and sets
    ``DEV_BYPASS_ALLOWED = True`` only for ``MIXAR_ENV=Dev`` builds. A user
    editing the bundled ``mixar.json`` to set ``environment=Dev`` cannot
    enable the bypass in a Prod/UAT build because the module that grants
    permission is not generated for those builds.

    Falls closed (returns ``('', '')``) when ``_build_env`` is absent — this
    is the case in source-tree imports (pytest, dev workflow before build).
    """
    try:
        from ._build_env import DEV_BYPASS_ALLOWED
    except ImportError:
        return ("", "")
    if not DEV_BYPASS_ALLOWED:
        return ("", "")
    config = get_config()
    bypass = config.get("dev_bypass", {})
    if not bypass.get("enabled", False):
        return ("", "")
    return (bypass.get("username", ""), bypass.get("password", ""))


def get_ui_mode() -> str:
    """Return the persisted UI mode. New users default to AI mode."""
    mode = get_config().get("ui_mode", UI_MODE_AI)
    return mode if mode in _UI_MODES else UI_MODE_AI


def set_ui_mode(mode: str) -> bool:
    """Persist the UI mode preference. Returns False on unknown mode or write failure."""
    if mode not in _UI_MODES:
        logger.error("Invalid ui_mode: %r", mode)
        return False
    return add_config("ui_mode", mode)


def get_frontend_url():
    """Get the frontend URL (resolved at build time via env vars).

    Used for browser-facing pages like SSO login.
    Falls back to the API server URL if frontend_url is not configured.
    """
    config = get_config()
    return config.get('frontend_url', get_server_url())
