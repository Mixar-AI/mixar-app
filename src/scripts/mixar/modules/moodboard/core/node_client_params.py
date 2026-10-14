# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Client-side node parameters that sit beside a model's catalog parameters.

A catalog parameter is a model input the backend adapter forwards. The
parameters here are NOT: each one selects how the client builds the payload
and is consumed before ``assemble_payload`` runs. ``node_schema`` mints them
as ordinary node parameter rows so the floating panel draws and resets them
like any other control.
"""

from __future__ import annotations

from mixar.modules.common.i18n import iface_, tip_

# The sidebar's PBR tab has a "Use Image Style Only" toggle that routes ONE
# reference image as Tripo style guidance (``style_ref_image_bytes_b64``)
# instead of a direct reference. The catalog does not publish it (it picks a
# payload key, it is not a model parameter), so the canvas node injects it.
# The label and description are the sidebar's, so one catalog entry
# translates both. ``node_mesh_execution._run_mesh_feature`` pops it from the
# params before the payload is assembled: it must never reach the backend.
PBR_STYLE_ONLY_PARAM = "style_only"


def injected_parameters(action_type: str) -> dict:
    """Specs (catalog shape) a node type adds beside the catalog's own."""
    if action_type != 'PBR_GEN':
        return {}
    return {
        PBR_STYLE_ONLY_PARAM: {
            "type": "boolean",
            "label": iface_("Use Image Style Only"),
            "description": tip_(
                "When enabled, only the image's artistic style is transferred "
                "(prompt still applies). When disabled, the image directly "
                "drives texture generation"
            ),
            "default": False,
            # Catalog params order from 0 upward; the toggle sits above them,
            # next to the reference sockets it qualifies.
            "order": -10,
        },
    }
