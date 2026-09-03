# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Onboarding's adapter onto the ``plugin_import`` module.

The tour's step-7 card offers to copy the user's existing Blender
add-ons across. Cards are GPU-painted with no Blender widgets, so the
card cannot host the per-plugin checklist that Preferences > Add-ons
does — during onboarding we import *everything* in one click and let
the user untick later. This module owns that one-click path plus the
scan result the card's copy is built from.

``plugin_import`` is imported lazily inside the functions: onboarding
must keep loading even if that module fails to import, and the UI
auto-discovery order between the two modules is not guaranteed.
"""

from __future__ import annotations

from dataclasses import dataclass

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# Cached for the lifetime of one tour run. The card's config is rebuilt
# on every redraw, so re-walking the filesystem there would hit the disk
# once per frame.
_scan_cache = None
_scan_done = False

_last_summary = None


@dataclass(frozen=True)
class ScanResult:
    """What the tour found to import, flattened for card copy."""

    version: str = ""
    count: int = 0

    @property
    def found(self) -> bool:
        return self.count > 0


@dataclass(frozen=True)
class ImportResult:
    """Outcome of the one-click import, flattened for card copy."""

    imported: int = 0
    already_present: int = 0
    enabled: int = 0
    failed: int = 0
    enable_failed: int = 0

    @property
    def had_problems(self) -> bool:
        return bool(self.failed or self.enable_failed)

    @property
    def did_nothing(self) -> bool:
        return not self.imported and not self.enabled


def scan(refresh: bool = False) -> ScanResult:
    """Find the best Blender install to import from.

    Cached — call with ``refresh=True`` to re-walk the disk (the tour
    does this once, when the user actually presses Import).
    """
    global _scan_cache, _scan_done

    if _scan_done and not refresh:
        return _scan_cache

    result = ScanResult()
    try:
        from mixar.modules.plugin_import.core.source_select import select_source

        choice = select_source()
        if choice is not None:
            result = ScanResult(version=choice.version, count=len(choice.plugins))
    except Exception as exc:  # noqa: BLE001 — never break the tour over this
        logger.warning("Onboarding plugin scan failed: %s", exc)

    _scan_cache = result
    _scan_done = True
    return result


def import_everything() -> ImportResult:
    """Copy in every discovered plugin and enable all of them.

    Returns a zeroed result on any failure — the outcome card reports
    honestly rather than the tour dying mid-flow.
    """
    global _last_summary

    try:
        from mixar.modules.plugin_import.core.importer import import_all
        from mixar.modules.plugin_import.core.source_select import select_source

        choice = select_source()
        if choice is None or not choice.has_plugins:
            _last_summary = ImportResult()
            return _last_summary

        # Onboarding enables everything — the card has no per-plugin UI.
        selection = {info.name: True for info in choice.plugins}
        summary = import_all(choice.plugins, selection)
        _last_summary = ImportResult(
            imported=summary.imported,
            already_present=summary.already_present,
            enabled=summary.enabled,
            failed=summary.failed,
            enable_failed=summary.enable_failed,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Onboarding plugin import failed: %s", exc, exc_info=True)
        _last_summary = ImportResult()

    logger.info("Onboarding plugin import result: %s", _last_summary)
    return _last_summary


def last_import_result() -> ImportResult:
    """The most recent import outcome, for the result card's copy."""
    return _last_summary if _last_summary is not None else ImportResult()


def import_ran() -> bool:
    """True once the one-click import has been attempted this tour.

    The offer card must not be re-shown after it has been answered with
    Import -- see ``steps._has_plugins_to_import``. Declining does not set
    this: a user who said "not now" may legitimately go Back and reconsider.
    """
    return _last_summary is not None


def reset() -> None:
    """Drop cached scan/import state so a re-run of the tour rescans."""
    global _scan_cache, _scan_done, _last_summary
    _scan_cache = None
    _scan_done = False
    _last_summary = None
