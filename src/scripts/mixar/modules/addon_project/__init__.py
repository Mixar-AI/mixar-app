# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Local, capability-scoped Blender add-on project workspace."""

from .service import AddonProjectService, get_addon_project_service

__all__ = ("AddonProjectService", "get_addon_project_service")
