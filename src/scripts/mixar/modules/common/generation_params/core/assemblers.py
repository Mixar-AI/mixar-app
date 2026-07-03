# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Payload assemblers — merge collected catalog params into each service's
EXISTING wire payload shape.

The backend job handlers keep their legacy payload contracts; the catalog
only changes where the parameter *values* come from (schema-driven UI
widgets), never the wire format. Each assembler maps ``collect_params()``
output (snake_case keys, typed values) onto the payload dict the service's
operator has always sent:

- ``model_3d``     → ``payload["params"] = {...}`` (Replicate/Tripo
  adapters read ``payload.get("params")`` and validate).
- ``image_to_3d``  → ``payload["sdk_params"]`` with Hunyuan-Pro PascalCase
  keys (GenerateType, Model, EnablePBR, Prompt?, FaceCount?, PolygonType?).
- ``hunyuan_rapid``→ ``payload["sdk_params"]`` with Rapid PascalCase keys
  (EnablePBR, EnableGeometry, ResultFormat? non-glb only, Prompt?).
- anything else    → ``payload["params"] = {...}`` (default).

Contract: ``assemble(params, payload, model_slug="") -> payload`` — mutates
and returns *payload*. ``model_slug`` is needed by services that derive a
wire field from the selected model (Hunyuan Pro's ``sdk_params["Model"]``
version comes from the ``hunyuan_pro_v3`` / ``hunyuan_pro_v3.1`` slug).
"""

from typing import Any, Callable, Dict

Assembler = Callable[[Dict[str, Any], Dict[str, Any], str], Dict[str, Any]]


def _pascal(key: str) -> str:
    """snake_case → PascalCase for unknown future sdk_params passthrough.

    Known keys use the explicit maps below (acronyms like ``enable_pbr`` →
    ``EnablePBR`` can't be derived mechanically).
    """
    return "".join(part.capitalize() for part in str(key).split("_") if part)


# ---------------------------------------------------------------------------
# model_3d (Trellis / Rodin / Tripo / Meshy via Replicate)
# ---------------------------------------------------------------------------


def _assemble_model_3d(
    params: Dict[str, Any], payload: Dict[str, Any], model_slug: str = ""
) -> Dict[str, Any]:
    """Wire shape: {image_bytes_b64, image_filename, prompt?} + params."""
    if params:
        payload["params"] = dict(params)
    return payload


# ---------------------------------------------------------------------------
# image_to_3d (Hunyuan Pro)
# ---------------------------------------------------------------------------


def _pro_model_version(model_slug: str) -> str:
    """hunyuan_pro_v3 → "3.0"; hunyuan_pro_v3.1 → "3.1" (default "3.0")."""
    if "_v" in (model_slug or ""):
        version = model_slug.rsplit("_v", 1)[1]
        if version:
            return version if "." in version else f"{version}.0"
    return "3.0"


def _assemble_image_to_3d(
    params: Dict[str, Any], payload: Dict[str, Any], model_slug: str = ""
) -> Dict[str, Any]:
    """Wire shape (matches the legacy Pro path in
    ``moodboard/core/generation_enqueue.py::_build_pro_payload``):
    {"sdk_params": {GenerateType, Model, EnablePBR, Prompt?, FaceCount?,
    PolygonType?}, image_bytes_b64?, image_filename?, multi_view_images?}.
    """
    params = dict(params or {})
    sdk = payload.setdefault("sdk_params", {})

    sdk["GenerateType"] = params.pop("generate_type", None) or "Normal"
    sdk["Model"] = _pro_model_version(model_slug)
    sdk["EnablePBR"] = bool(params.pop("enable_pbr", False))

    prompt = params.pop("prompt", None)
    if prompt:
        sdk["Prompt"] = prompt
    # face_count / polygon_type are visible_if generate_type=LowPoly in the
    # catalog schema — collect_params() already omits them in Normal mode.
    face_count = params.pop("face_count", None)
    if face_count:
        sdk["FaceCount"] = int(face_count)
    polygon_type = params.pop("polygon_type", None)
    if polygon_type:
        sdk["PolygonType"] = polygon_type

    for key, value in params.items():
        sdk.setdefault(_pascal(key), value)
    return payload


# ---------------------------------------------------------------------------
# hunyuan_rapid (Rapid 3D)
# ---------------------------------------------------------------------------


def _assemble_hunyuan_rapid(
    params: Dict[str, Any], payload: Dict[str, Any], model_slug: str = ""
) -> Dict[str, Any]:
    """Wire shape (matches ``hunyuan_ops.py::_submit_rapid_queue``):
    {"sdk_params": {EnablePBR, EnableGeometry, ResultFormat? (non-glb
    only), Prompt?}, image_bytes_b64?, image_filename?}.
    """
    params = dict(params or {})
    sdk = payload.setdefault("sdk_params", {})

    sdk["EnablePBR"] = bool(params.pop("enable_pbr", False))
    sdk["EnableGeometry"] = bool(params.pop("enable_geometry", False))

    result_format = params.pop("result_format", None)
    if result_format and str(result_format).lower() != "glb":
        sdk["ResultFormat"] = str(result_format).lower()
    prompt = params.pop("prompt", None)
    if prompt:
        sdk["Prompt"] = prompt

    for key, value in params.items():
        sdk.setdefault(_pascal(key), value)
    return payload


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def _assemble_default(
    params: Dict[str, Any], payload: Dict[str, Any], model_slug: str = ""
) -> Dict[str, Any]:
    """Unknown services: pass catalog params through as payload["params"]."""
    if params:
        payload["params"] = dict(params)
    return payload


_ASSEMBLERS: Dict[str, Assembler] = {
    "model_3d": _assemble_model_3d,
    "image_to_3d": _assemble_image_to_3d,
    "hunyuan_rapid": _assemble_hunyuan_rapid,
}


def get_assembler(service_key: str) -> Assembler:
    """The assembler for a service key (default passthrough for unknown)."""
    return _ASSEMBLERS.get(service_key, _assemble_default)


def assemble_payload(
    service_key: str,
    params: Dict[str, Any],
    payload: Dict[str, Any],
    model_slug: str = "",
) -> Dict[str, Any]:
    """Merge *params* into *payload* using the service's wire contract."""
    return get_assembler(service_key)(params, payload, model_slug)
