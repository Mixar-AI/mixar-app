# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Process identity survives .blend loads; RNA is only its UI mirror."""

import uuid

_instance_id = str(uuid.uuid4())


def instance_id(window_manager):
    if window_manager is None or not hasattr(window_manager, "mixie_instance_id"):
        return ""
    if window_manager.mixie_instance_id != _instance_id:
        window_manager.mixie_instance_id = _instance_id
    return _instance_id
