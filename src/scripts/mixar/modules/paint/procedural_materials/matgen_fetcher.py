# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Auth, URL, and cache-directory helpers for the material registry.

Kept separate from material_registry.py to stay under the 500-line limit and
to allow testing auth/URL logic independently of Blender's bpy module.
"""
import os


def _get_auth_token() -> str:
    try:
        from ...auth.core.auth import get_access_token
        return get_access_token() or ""
    except Exception:
        return ""


def _get_base_url() -> str:
    try:
        from ....config.config import get_server_url
        return get_server_url() or ""
    except Exception:
        return ""


def _get_cache_dir() -> str:
    """Return (and create) the local script cache directory."""
    try:
        import bpy
        cache_dir = bpy.utils.user_resource('DATAFILES', path='mixar/material_cache')
    except Exception:
        cache_dir = os.path.join(os.path.expanduser("~"), ".mixar", "material_cache")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir
