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
        # Capability mode selector (Mode → Model → params)
        get_service_enum_items,   # Mode dropdown items for a capability
        resolve_service_key,      # mode enum value -> valid service key
        resolve_model_slug,       # model enum value -> valid model slug
        draw_capability_selector, # render Mode/Model dropdowns + params
        # Wire payload assembly
        assemble_payload,         # merge catalog params into wire payloads
        get_assembler,
    )

See ``core/engine.py`` for the dynamic-PropertyGroup design decision,
``core/selector.py`` for the capability mode selector, and
``core/assemblers.py`` for the per-service wire contracts.
"""

from .core.engine import (
    collect_params,
    has_params,
    rebuild_from_catalog,
    unregister_all_param_groups,
)
from .core.draw import draw_service_params
from .core.selector import (
    draw_capability_selector,
    get_service_enum_items,
    resolve_model_slug,
    resolve_service_key,
)
from .core.assemblers import assemble_payload, get_assembler

__all__ = (
    "collect_params",
    "has_params",
    "rebuild_from_catalog",
    "unregister_all_param_groups",
    "draw_service_params",
    "get_service_enum_items",
    "resolve_service_key",
    "resolve_model_slug",
    "draw_capability_selector",
    "assemble_payload",
    "get_assembler",
)
