# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Schema-driven generation parameter engine.

Turns the backend generation catalog's per-model parameter schemas into
real Blender properties and collects their current values as plain dicts
for payload building. Param key sets vary per model and change from the DB
without client releases — nothing here hardcodes parameter names.

DESIGN DECISION — dynamic PropertyGroups on WindowManager
=========================================================
Two approaches were evaluated (per the project plan):

1. Dynamically build + register a PropertyGroup per (service, model) at
   catalog-load time (``type()`` + ``bpy.utils.register_class``,
   re-registered when the catalog changes).
2. A generic CollectionProperty of typed param-value items attached once
   at startup, synced to the schema at draw time.

We use approach 1, with one deliberate twist: the groups are attached to
``bpy.types.WindowManager`` (not Scene). Rationale:

- The classic fragility of re-registering PropertyGroups comes from
  *persisted* data: Scene-attached groups are serialized into .blend files
  and participate in the undo stack, so unregistering a class mid-session
  invalidates existing scene data. WindowManager properties are neither
  saved to .blend files nor tracked by undo, so tearing down and
  re-registering on a catalog swap is safe.
- Rebuilds only ever run on the main thread, via a ``bpy.app.timers``
  callback scheduled by ``generation_catalog_cache`` after a payload swap
  — the same handler-sets-flag / timer-does-work pattern used across this
  codebase. Timers never run during draw, so no draw callback can hold a
  reference to a half-unregistered class.
- Real ``IntProperty``/``FloatProperty`` min/max and ``EnumProperty``
  items give native widgets (bounded sliders, dropdowns, expanded enums)
  for free. The collection fallback would need get/set indirection hacks
  to fake bounds and enum storage — approach 2's complexity lives in every
  draw/collect call, approach 1's only in the (rare) rebuild.

Trade-off: WindowManager values are per-session (not saved in .blend).
That matches the semantics of generation settings and is the price of
robust re-registration. Values are snapshotted and restored across catalog
rebuilds where the param still exists and accepts the old value.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

import bpy

from mixar.config.logging_config import get_logger
from ..constants import (
    FLOAT_TYPES,
    PARAM_ATTR_PREFIX,
    TYPE_BOOLEAN,
    TYPE_INTEGER,
    UNBOUNDED_FLOAT_MAX,
    UNBOUNDED_FLOAT_MIN,
    UNBOUNDED_INT_MAX,
    UNBOUNDED_INT_MIN,
    WM_ATTR_PREFIX,
)

logger = get_logger(__name__)

# (service_key, model_slug) -> WindowManager attribute name
_registered: Dict[Tuple[str, str], str] = {}
# (service_key, model_slug) -> generated PropertyGroup class
_classes: Dict[Tuple[str, str], type] = {}
# (service_key, model_slug) -> {param_name: {"spec", "attr", "value_map"}}
# value_map maps enum identifier strings back to the original (possibly
# non-string, e.g. int) choice values.
_schemas: Dict[Tuple[str, str], Dict[str, Dict[str, Any]]] = {}


def _sanitize(name: str) -> str:
    return re.sub(r"\W", "_", str(name))


def _wm_attr(service_key: str, model_slug: str) -> str:
    return f"{WM_ATTR_PREFIX}{_sanitize(service_key)}__{_sanitize(model_slug)}"


# ============================================================================
# PROPERTY BUILDING
# ============================================================================


def _normalized_choices(spec: dict) -> List[dict]:
    """Return [{"value", "label"}] from either `choices` or `enum`."""
    choices = spec.get("choices")
    if choices:
        return [c for c in choices if c.get("value") is not None]
    enum = spec.get("enum")
    if enum:
        return [{"value": v, "label": str(v)} for v in enum if v is not None]
    return []


def _make_prop(param_name: str, spec: dict):
    """Build a bpy property for one schema param.

    Returns (property, value_map) — value_map is only set for enum-backed
    params and maps identifier strings to original choice values.
    """
    from bpy.props import (
        BoolProperty,
        EnumProperty,
        FloatProperty,
        IntProperty,
        StringProperty,
    )

    ptype = spec.get("type") or "string"
    label = spec.get("label") or param_name.replace("_", " ").title()
    description = spec.get("description") or ""
    default = spec.get("default")
    choices = _normalized_choices(spec)

    if choices:
        items = []
        value_map: Dict[str, Any] = {}
        for choice in choices:
            ident = str(choice["value"])
            if not ident:
                continue
            items.append((ident, str(choice.get("label") or ident), ""))
            value_map[ident] = choice["value"]
        if not items:
            return None, None
        default_id = str(default) if default is not None else items[0][0]
        if default_id not in value_map:
            default_id = items[0][0]
        return (
            EnumProperty(
                name=label, description=description, items=items, default=default_id
            ),
            value_map,
        )

    if ptype == TYPE_BOOLEAN:
        return (
            BoolProperty(name=label, description=description, default=bool(default)),
            None,
        )

    if ptype == TYPE_INTEGER:
        pmin = spec.get("min")
        pmax = spec.get("max")
        return (
            IntProperty(
                name=label,
                description=description,
                default=int(default) if default is not None else 0,
                min=int(pmin) if pmin is not None else UNBOUNDED_INT_MIN,
                max=int(pmax) if pmax is not None else UNBOUNDED_INT_MAX,
            ),
            None,
        )

    if ptype in FLOAT_TYPES:
        pmin = spec.get("min")
        pmax = spec.get("max")
        return (
            FloatProperty(
                name=label,
                description=description,
                default=float(default) if default is not None else 0.0,
                min=float(pmin) if pmin is not None else UNBOUNDED_FLOAT_MIN,
                max=float(pmax) if pmax is not None else UNBOUNDED_FLOAT_MAX,
            ),
            None,
        )

    # string / anything unknown → text field
    return (
        StringProperty(
            name=label,
            description=description,
            default=str(default) if default is not None else "",
        ),
        None,
    )


def _build_group(service_key: str, model_slug: str, parameters: dict):
    """Create (but don't register) a PropertyGroup class + schema store."""
    annotations: Dict[str, Any] = {}
    schema: Dict[str, Dict[str, Any]] = {}

    for param_name, spec in (parameters or {}).items():
        if not isinstance(spec, dict):
            continue
        if spec.get("visible") is False:
            # Pre-filtered server-side, but stay defensive.
            continue
        attr = PARAM_ATTR_PREFIX + _sanitize(param_name)
        prop, value_map = _make_prop(param_name, spec)
        if prop is None:
            continue
        annotations[attr] = prop
        schema[param_name] = {"spec": spec, "attr": attr, "value_map": value_map}

    cls = type(
        f"MIXAR_PG_genparams_{_sanitize(service_key)}__{_sanitize(model_slug)}",
        (bpy.types.PropertyGroup,),
        {"__annotations__": annotations},
    )
    return cls, schema


# ============================================================================
# REBUILD / TEARDOWN (main thread only)
# ============================================================================


def _snapshot_values() -> Dict[Tuple[str, str], Dict[str, Any]]:
    """Capture current raw attr values before a rebuild."""
    snapshot: Dict[Tuple[str, str], Dict[str, Any]] = {}
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return snapshot
    for key, attr in _registered.items():
        group = getattr(wm, attr, None)
        schema = _schemas.get(key) or {}
        if group is None:
            continue
        values = {}
        for param_name, entry in schema.items():
            try:
                values[param_name] = getattr(group, entry["attr"])
            except Exception:
                pass
        if values:
            snapshot[key] = values
    return snapshot


def _restore_values(snapshot: Dict[Tuple[str, str], Dict[str, Any]]) -> None:
    """Re-apply snapshotted values where the param still exists and the old
    value is still acceptable (stale values are silently ignored)."""
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return
    for key, values in snapshot.items():
        schema = _schemas.get(key)
        attr = _registered.get(key)
        if not schema or not attr:
            continue
        group = getattr(wm, attr, None)
        if group is None:
            continue
        for param_name, value in values.items():
            entry = schema.get(param_name)
            if not entry:
                continue  # Param no longer exists — not an error.
            try:
                setattr(group, entry["attr"], value)
            except Exception:
                pass  # Old value no longer valid (e.g. enum id removed).


def _teardown() -> None:
    """Detach and unregister every generated group."""
    for key, attr in list(_registered.items()):
        try:
            if hasattr(bpy.types.WindowManager, attr):
                delattr(bpy.types.WindowManager, attr)
        except Exception:
            pass
        cls = _classes.get(key)
        if cls is not None:
            try:
                bpy.utils.unregister_class(cls)
            except Exception:
                pass
    _registered.clear()
    _classes.clear()
    _schemas.clear()


def rebuild_from_catalog() -> None:
    """(Re)build all param groups from the current catalog cache.

    MUST run on the main thread — scheduled via ``bpy.app.timers`` by
    ``generation_catalog_cache`` after a payload swap. Safe to call
    repeatedly; existing values are preserved where params still exist.
    """
    from bpy.props import PointerProperty

    try:
        from mixar.bootstrap.generation_catalog_cache import get_capabilities
    except ImportError:
        return

    capabilities = get_capabilities()
    if not capabilities:
        return

    snapshot = _snapshot_values()
    _teardown()

    count = 0
    for capability in capabilities:
        for service in capability.get("services") or []:
            service_key = service.get("key")
            if not service_key:
                continue
            for model in service.get("models") or []:
                slug = model.get("slug")
                if not slug:
                    continue
                try:
                    cls, schema = _build_group(
                        service_key, slug, model.get("parameters") or {}
                    )
                    bpy.utils.register_class(cls)
                    attr = _wm_attr(service_key, slug)
                    setattr(
                        bpy.types.WindowManager, attr, PointerProperty(type=cls)
                    )
                    key = (service_key, slug)
                    _registered[key] = attr
                    _classes[key] = cls
                    _schemas[key] = schema
                    count += 1
                except Exception as exc:
                    logger.error(
                        "Param group build failed for %s/%s: %s",
                        service_key, slug, exc,
                    )

    _restore_values(snapshot)
    logger.info("Generation param engine rebuilt (%d model groups)", count)


def unregister_all_param_groups() -> None:
    """Shutdown hook — tear down all dynamic classes and WM attributes."""
    _teardown()


# ============================================================================
# ACCESS / VALUE COLLECTION
# ============================================================================


def has_params(service_key: str, model_slug: str) -> bool:
    """True when a param group exists for (service, model) — i.e. the
    catalog is loaded and the engine has been rebuilt from it."""
    return (service_key, model_slug) in _registered


def get_schema(service_key: str, model_slug: str) -> Optional[Dict[str, Dict[str, Any]]]:
    return _schemas.get((service_key, model_slug))


def get_param_group(service_key: str, model_slug: str):
    """The live WindowManager property group instance, or None."""
    attr = _registered.get((service_key, model_slug))
    if not attr:
        return None
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return None
    return getattr(wm, attr, None)


def read_param_value(group, entry: Dict[str, Any]):
    """Read one param's current value with proper python type (enum
    identifiers are mapped back to original choice values, e.g. int)."""
    raw = getattr(group, entry["attr"])
    value_map = entry.get("value_map")
    if value_map is not None:
        return value_map.get(raw, raw)
    return raw


def is_param_visible(
    schema: Dict[str, Dict[str, Any]], group, param_name: str
) -> bool:
    """Evaluate `visible` and `visible_if` for one param against current
    values. `visible_if` is {"<other_param>": "<value>"} — hide unless the
    other param currently equals the value (string-compared)."""
    entry = schema.get(param_name)
    if entry is None:
        return False
    spec = entry["spec"]
    if spec.get("visible") is False:
        return False
    condition = spec.get("visible_if")
    if condition:
        for other_name, expected in condition.items():
            other_entry = schema.get(other_name)
            if other_entry is None:
                return False
            current = read_param_value(group, other_entry)
            if str(current) != str(expected):
                return False
    return True


def sorted_param_names(schema: Dict[str, Dict[str, Any]]) -> List[str]:
    """Param names honoring the schema `order` field."""
    return sorted(
        schema.keys(),
        key=lambda name: (schema[name]["spec"].get("order") or 0, name),
    )


def collect_params(service_key: str, model_slug: str) -> Dict[str, Any]:
    """Current values of all visible/applicable params as a plain dict.

    Returns {} when the engine has no group for (service, model) — e.g.
    catalog not loaded — so callers can fall back to legacy paths. Values
    keep proper python types (int stays int for integer enums like
    resolution [512, 1024, 2048]).
    """
    key = (service_key, model_slug)
    schema = _schemas.get(key)
    group = get_param_group(service_key, model_slug)
    if not schema or group is None:
        return {}

    out: Dict[str, Any] = {}
    for param_name in sorted_param_names(schema):
        if not is_param_visible(schema, group, param_name):
            continue
        try:
            out[param_name] = read_param_value(group, schema[param_name])
        except Exception as exc:
            logger.debug("collect_params: read failed for %s: %s", param_name, exc)
    return out
