# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Small atomic JSON store used only on the Blender client."""

import json
from pathlib import Path

# Shared with other client modules; re-exported for this package's callers.
from mixar.modules.common.utils.atomic_json import write_json_atomic  # noqa: F401


def read_json(path: Path, default):
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return default
