# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Schema-driven generation parameter engine (catalog → Blender widgets).

Public surface:
    from mixar.modules.common.generation_params import (
        rebuild_from_catalog,     # (re)build param groups from catalog cache
        has_params,               # engine has a group for (service, model)?
        collect_params,           # current values -> plain dict for payloads
        draw_service_params,      # render a model's params into a layout
        unregister_all_param_groups,
    )

See ``core/engine.py`` for the dynamic-PropertyGroup design decision.
"""

from .core.engine import (
    collect_params,
    has_params,
    rebuild_from_catalog,
    unregister_all_param_groups,
)
from .core.draw import draw_service_params

__all__ = (
    "collect_params",
    "has_params",
    "rebuild_from_catalog",
    "unregister_all_param_groups",
    "draw_service_params",
)
