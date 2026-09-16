# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

SCHEMA_VERSION = 1
COLLECTION_NAME = "Rendered Meshes"

# CAD car convention used by the six-view helper: front is -X, up is +Z.
SIX_VIEW_AXES = {
    "front": (-1, 0, 0),
    "rear": (1, 0, 0),
    "left": (0, -1, 0),
    "right": (0, 1, 0),
    "top": (0, 0, 1),
    "bottom": (0, 0, -1),
}
SIX_VIEW_COLLECTION = "Exterior - Six View Union"
