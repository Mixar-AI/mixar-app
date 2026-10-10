# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Rebuild the open AI Provider Settings dialog when its data changes.

A props dialog is a popup block: tagging areas for redraw repaints it but
never re-runs its ``draw()``, so rows built from the models catalog stayed
on "Loading…" when the catalog landed after the dialog opened. A popup's
region is ``TEMPORARY`` and supports ``tag_refresh_ui()``, which rebuilds
the block. The dialog operator records its region on every draw and
forgets it when the dialog closes; async callbacks call ``refresh()``.
"""

_region = None


def remember(region) -> None:
    """Called from the dialog's draw(): the popup's own region."""
    global _region
    _region = region


def forget() -> None:
    """Called when the dialog closes — the region is freed with it."""
    global _region
    _region = None


def refresh() -> None:
    """Rebuild the open dialog, if any. Main thread only."""
    if _region is None:
        return
    try:
        _region.tag_refresh_ui()
    except Exception:  # noqa: BLE001 — region already gone or not a popup
        forget()


classes = ()
