# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Build the path-free context attached to a project-mode chat turn."""

from .constants import PROTOCOL_VERSION
from .errors import AddonProjectError
from .service import get_addon_project_service


def build_project_context(scene) -> dict:
    project_id = str(getattr(scene, "mixie_addon_project_id", "") or "")
    if not project_id:
        raise AddonProjectError("project_not_linked", "Link an add-on project folder before sending")
    service = get_addon_project_service()
    description = service.describe(project_id)
    lease = service.issue_lease(project_id)
    return {
        "mode": "addon_project",
        "protocol_version": PROTOCOL_VERSION,
        "project_id": project_id,
        "lease_id": lease["lease_id"],
        "revision": description["revision"],
    }
