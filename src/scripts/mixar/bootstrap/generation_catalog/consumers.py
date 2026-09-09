# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fan a catalog swap out to everything built from the catalog.

Split out of ``generation_catalog_cache.py`` (500-line rule), which owns
fetching, storing and querying the payload; who has to be told about a new one
is a separate concern.

Each consumer gets its OWN try block and its OWN log line. They are independent
-- the sidebar's parameter engine, the moodboard's saved nodes, and the sidebar
tab labels are rebuilt from the same payload but nothing else -- and sharing a
block silently coupled them: the node refresh sat inside the engine's try with
its import, so anything raising earlier (including the blanket ``ImportError``
that exists for "the params module is not loaded yet") skipped the node sweep
with no log line, leaving every node on the board showing its previous
dropdowns while the sidebar updated.

Runs on a main-thread timer: `bpy` class re-registration requires it.
"""

import logging

logger = logging.getLogger(__name__)


def _rebuild_parameter_engine() -> None:
    """Rebuild the sidebar's per-(service, model) PropertyGroups."""
    try:
        from mixar.modules.common.generation_params.core.engine import (
            rebuild_from_catalog,
        )

        rebuild_from_catalog()
    except ImportError:
        pass
    except Exception as exc:
        logger.error("Generation param engine rebuild failed: %s", exc)


def _refresh_moodboard_nodes() -> None:
    """Re-resolve every saved inference node against the new catalog."""
    try:
        from mixar.modules.moodboard.core.node_schema import sync_all_node_schemas

        sync_all_node_schemas()
    except ImportError:
        pass
    except Exception as exc:
        logger.error("Moodboard node catalog refresh failed: %s", exc)


def _refresh_sidebar_tab_labels() -> None:
    """Re-register moodboard sidebar tabs whose capability label was renamed.

    A no-op until the panels module loads, and when nothing changed.
    """
    try:
        from mixar.modules.moodboard.ui.moodboard_tab_labels import refresh_tab_labels

        refresh_tab_labels()
    except Exception as exc:
        logger.error("Moodboard tab label refresh failed: %s", exc)


def notify_catalog_swapped() -> None:
    """Tell every catalog consumer that a new payload is live."""
    _rebuild_parameter_engine()
    _refresh_moodboard_nodes()
    _refresh_sidebar_tab_labels()
