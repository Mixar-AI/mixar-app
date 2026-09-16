# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Versioned client RPC for catalog search, exact asset placement, and scattering."""

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def run_tool(scene, name, params=None):
    from .catalog import service
    params = params or {}
    try:
        if name == 'list_libraries':
            return service.status()
        if name == 'refresh_libraries':
            return service.refresh()
        if name == 'search':
            return service.search(**params)
        if name == 'scatter':
            from .scatter import scatter
            return scatter(scene, **params)
        if name == 'append':
            from .asset_source import append_asset
            return append_asset(scene, **params)
        raise ValueError('Unknown asset catalog operation')
    except (ValueError, TypeError) as exc:
        return {'success': False, 'error': str(exc)}
    except Exception:
        logger.exception('Asset catalog operation failed: %s', name)
        return {'success': False, 'error': 'Asset operation failed; refresh the library and retry'}
