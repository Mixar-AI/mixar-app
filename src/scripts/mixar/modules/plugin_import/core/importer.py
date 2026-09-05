# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Copy discovered plugins into Mixar and enable the selected ones.

Flow (all steps resilient — one bad plugin never aborts the batch):

1. Copy every discovered plugin's files into Mixar's user tree. Add-ons
   go to ``user_resource('SCRIPTS')/addons``; extensions are consolidated
   into Mixar's ``user_default`` extension repo dir. Already-present
   plugins are left untouched (idempotent).
2. Refresh: ``bpy.utils.refresh_script_paths()`` so a just-created
   addons dir is importable, ``preferences.addon_refresh`` for add-ons,
   and the *offline*
   ``extensions.repo_refresh_all`` so copied extension packages are
   scanned from their local ``blender_manifest.toml`` (no network).
3. Enable each plugin whose checkbox is ticked via ``addon_utils.enable``.
4. Persist with ``wm.save_userpref``.

Returns an :class:`ImportSummary` the operator surfaces as a popup and
mirrors back into the checklist rows.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

import addon_utils
import bpy

from mixar.config.logging_config import get_logger

from ..constants import (
    DEFAULT_USER_REPO,
    ENABLE_FAILED,
    ENABLE_OK,
    ENABLE_SKIPPED,
    EXTENSION_MODULE_PREFIX,
    KIND_EXTENSION,
    STATUS_EXISTS,
    STATUS_FAILED,
    STATUS_IMPORTED,
)
from .enumerate import PluginInfo

logger = get_logger(__name__)

# Never copy compiled-python cruft along with a plugin's sources.
_COPY_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")


@dataclass
class ItemOutcome:
    """Per-plugin result threaded back to the checklist row."""

    name: str
    kind: str
    import_status: str            # STATUS_IMPORTED | STATUS_EXISTS | STATUS_FAILED
    enable_status: str = ""       # ENABLE_OK | ENABLE_SKIPPED | ENABLE_FAILED | ""
    message: str = ""


@dataclass
class ImportSummary:
    imported: int = 0
    already_present: int = 0
    failed: int = 0
    enabled: int = 0
    enable_failed: int = 0
    items: list[ItemOutcome] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Mixar target directories
# ---------------------------------------------------------------------------


class PluginImportUnavailable(RuntimeError):
    """Mixar's own user tree could not be resolved — nothing can be imported."""


def _require_dir(raw: str, what: str) -> Path:
    """Turn a ``user_resource`` result into a Path, refusing the empty string.

    ``bpy.utils.user_resource`` PRINTS and swallows a creation failure and
    returns ``""``. ``Path("")`` is ``Path(".")``, so an unguarded call
    redirects the entire import into the process CWD — on Windows typically
    the install directory — while every row still reports "imported". Most
    likely on Windows (redirected/roaming ``%APPDATA%``, OneDrive-backed
    profiles, locked-down machines), so fail the batch loudly instead.
    """
    if not raw:
        raise PluginImportUnavailable(
            "Could not create Mixar's {} directory — check permissions on your "
            "user profile folder.".format(what)
        )
    return Path(raw)


def mixar_addons_dir() -> Path:
    """Mixar's user add-ons dir (``.../Mixar/5.0/scripts/addons``)."""
    return _require_dir(
        bpy.utils.user_resource("SCRIPTS", path="addons", create=True), "add-ons"
    )


def target_extension_repo() -> tuple[str, Path]:
    """Resolve the Mixar extension repo to import into.

    Prefers the standard local ``user_default`` repo; otherwise the first
    non-remote USER-source repo. Falls back to synthesising the
    ``user_default`` path under ``user_resource('EXTENSIONS')`` if no repo
    is registered (enable may then be a no-op, but the files still land).
    Returns ``(repo_module, repo_directory)``.
    """
    repos = getattr(bpy.context.preferences.extensions, "repos", None) or []

    preferred = None
    fallback = None
    for repo in repos:
        if getattr(repo, "source", "USER") != "USER":
            continue
        if getattr(repo, "use_remote_url", False):
            continue
        directory = getattr(repo, "directory", "") or ""
        if not directory:
            continue
        if repo.module == DEFAULT_USER_REPO:
            preferred = (repo.module, Path(directory))
            break
        if fallback is None:
            fallback = (repo.module, Path(directory))

    chosen = preferred or fallback
    if chosen is None:
        # No usable repo registered — synthesise the default path.
        path = _require_dir(
            bpy.utils.user_resource("EXTENSIONS", path=DEFAULT_USER_REPO, create=True),
            "extensions",
        )
        return DEFAULT_USER_REPO, path

    module, directory = chosen
    directory.mkdir(parents=True, exist_ok=True)
    return module, directory


def _extension_module_id(repo_module: str, pkg_id: str) -> str:
    return f"{EXTENSION_MODULE_PREFIX}.{repo_module}.{pkg_id}"


# ---------------------------------------------------------------------------
# Copy one plugin in
# ---------------------------------------------------------------------------


def _copy_in(src: Path, dst: Path, is_dir: bool) -> str:
    """Copy ``src`` → ``dst``. Returns STATUS_EXISTS if already there."""
    if dst.exists():
        return STATUS_EXISTS
    dst.parent.mkdir(parents=True, exist_ok=True)
    if is_dir:
        shutil.copytree(src, dst, ignore=_COPY_IGNORE)
    else:
        shutil.copy2(src, dst)
    return STATUS_IMPORTED


def _import_one(
    info: PluginInfo, addons_dir: Path, repo_module: str, repo_dir: Path
) -> tuple[ItemOutcome, str | None]:
    """Copy a single plugin. Returns (outcome, enable_module_id | None)."""
    try:
        if info.kind == KIND_EXTENSION:
            dst = repo_dir / info.name
            status = _copy_in(info.path, dst, is_dir=True)
            enable_id = _extension_module_id(repo_module, info.name)
        else:
            suffix = "" if info.is_dir else ".py"
            dst = addons_dir / f"{info.name}{suffix}"
            status = _copy_in(info.path, dst, info.is_dir)
            enable_id = info.name
        return ItemOutcome(info.name, info.kind, status), enable_id
    except Exception as exc:  # noqa: BLE001 — one plugin must not abort the batch
        logger.error("Failed to import plugin %s: %s", info.name, exc)
        return ItemOutcome(info.name, info.kind, STATUS_FAILED, message=str(exc)), None


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def import_all(plugins: list[PluginInfo], selection: dict[str, bool]) -> ImportSummary:
    """Import every plugin in ``plugins``; enable those ticked in ``selection``.

    ``selection`` maps ``PluginInfo.name`` → enable-after-import bool.
    """
    summary = ImportSummary()
    try:
        addons_dir = mixar_addons_dir()
        repo_module, repo_dir = target_extension_repo()
    except PluginImportUnavailable as exc:
        # No usable destination: report every plugin as failed with the real
        # reason rather than copying anything into the working directory.
        logger.error("Plugin import aborted: %s", exc)
        summary.failed = len(plugins)
        summary.items = [
            ItemOutcome(info.name, info.kind, STATUS_FAILED, message=str(exc))
            for info in plugins
        ]
        return summary

    # 1. Copy all files in first.
    enable_ids: dict[str, str] = {}   # plugin name -> enable module id
    any_extension = False
    for info in plugins:
        outcome, enable_id = _import_one(info, addons_dir, repo_module, repo_dir)
        summary.items.append(outcome)
        if outcome.import_status == STATUS_IMPORTED:
            summary.imported += 1
        elif outcome.import_status == STATUS_EXISTS:
            summary.already_present += 1
        else:
            summary.failed += 1
        if enable_id is not None:
            enable_ids[info.name] = enable_id
            if info.kind == KIND_EXTENSION:
                any_extension = True

    # 2. Refresh so freshly-copied plugins are visible to the enable step.
    _refresh(any_extension)

    # 3. Enable the ticked plugins (that copied in OK).
    for outcome in summary.items:
        if outcome.import_status == STATUS_FAILED:
            continue
        if not selection.get(outcome.name, False):
            outcome.enable_status = ENABLE_SKIPPED
            continue
        module_id = enable_ids.get(outcome.name)
        if module_id is None:
            outcome.enable_status = ENABLE_FAILED
            summary.enable_failed += 1
            continue
        ok, err = _enable(module_id)
        if ok:
            outcome.enable_status = ENABLE_OK
            summary.enabled += 1
        else:
            outcome.enable_status = ENABLE_FAILED
            summary.enable_failed += 1
            outcome.message = err or "enable failed (may be incompatible with Blender 5.0)"

    # 4. Persist enabled state.
    if summary.enabled:
        _save_userpref()

    logger.info(
        "Plugin import: %d imported, %d already present, %d failed, "
        "%d enabled, %d enable-failed",
        summary.imported, summary.already_present, summary.failed,
        summary.enabled, summary.enable_failed,
    )
    return summary


def _refresh(any_extension: bool) -> None:
    """Make freshly-copied plugins importable, then rescan their metadata.

    ``refresh_script_paths()`` is the ONLY thing that appends Mixar's user
    ``scripts/addons`` to ``sys.path`` (it is the sole caller of
    ``addon_utils.paths()`` for that purpose). On a fresh profile that
    directory does not exist at startup, so ``addon_utils.paths()`` skipped
    it and nothing put it on the path -- ``mixar_addons_dir(create=True)``
    only just created it, moments ago, in :func:`import_all`. Without this
    call every legacy add-on copies in fine and then fails to enable with a
    ModuleNotFoundError, because ``preferences.addon_refresh`` runs only
    ``addon_utils.modules_refresh()``, which rebuilds the bl_info cache and
    never touches ``sys.path``. Blender's own ``PREFERENCES_OT_addon_install``
    calls it for exactly this reason.

    Platform-neutral, and needed on all three: the missing-directory case is
    identical for ``%APPDATA%/Mixar/5.0/scripts/addons`` on Windows and
    ``~/.config/Mixar/5.0/scripts/addons`` on Linux.
    """
    try:
        bpy.utils.refresh_script_paths()
    except Exception as exc:  # noqa: BLE001
        logger.error("refresh_script_paths failed: %s", exc)
    try:
        bpy.ops.preferences.addon_refresh()
    except Exception as exc:  # noqa: BLE001
        logger.error("addon_refresh failed: %s", exc)
    if any_extension:
        try:
            # Offline rescan of local package manifests — no network.
            bpy.ops.extensions.repo_refresh_all()
        except Exception as exc:  # noqa: BLE001
            logger.error("repo_refresh_all failed: %s", exc)


def _enable(module_id: str) -> tuple[bool, str]:
    """Enable one plugin. Returns (ok, error_message).

    ``addon_utils.enable`` does NOT propagate the failure: its default
    ``handle_error`` prints a traceback and it returns ``None``. So an
    incompatible ``blender_version_min``, a broken ``register()`` or a
    missing dependency all reached the panel as the generic "add-on not
    found after import". Passing our own handler captures the real reason
    so the row can show it without sending the user to the console.
    """
    captured: list[str] = []

    def _capture(exc: BaseException) -> None:
        captured.append(f"{type(exc).__name__}: {exc}")
        logger.error("Enable failed for %s: %s", module_id, exc)

    try:
        mod = addon_utils.enable(
            module_id, default_set=True, persistent=True, handle_error=_capture
        )
    except Exception as exc:  # noqa: BLE001 — one plugin must not abort the batch
        logger.error("Enable failed for %s: %s", module_id, exc)
        return False, f"{type(exc).__name__}: {exc}"
    if mod is not None:
        return True, ""
    if captured:
        return False, captured[0]
    return False, "add-on not found after import"


def _save_userpref() -> None:
    try:
        bpy.ops.wm.save_userpref()
    except Exception as exc:  # noqa: BLE001
        logger.error("save_userpref failed: %s", exc)
