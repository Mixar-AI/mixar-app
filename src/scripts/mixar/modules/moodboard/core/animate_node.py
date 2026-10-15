# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Animate card: preset animations retargeted onto a connected rig.

No export: the payload names the Auto Rig job (``rig_job_id``) the backend
already holds, read from the ``mixar_rig_job_id`` stamp on the connected
character, plus the card's catalog params. Only a rig stamped with its
skeleton (``mixar_rig_skeleton``) can take presets: the rig job reports one
for a retargetable rig alone, so a rig without it is refused up front. The
result's clips are merged onto that same character
(``hunyuan.core.animation_merge``), and the card's result IS the character —
armature and meshes — so another Animate card or an export chains off it.
"""

from __future__ import annotations

from mixar.modules.common.i18n import rpt_
from mixar.modules.hunyuan.constants import (
    ANIMATE_PRESETS_PARAM,
    ANIMATION_CAPABILITY,
)
from mixar.modules.hunyuan.core.animate_enqueue import (
    enqueue_retarget_job,
    find_rig_job_id,
    find_rig_skeleton,
)
from mixar.modules.hunyuan.core.animate_presets import (
    NOT_A_RIG,
    preset_error,
    preset_skeleton,
    rig_refusal,
)
from mixar.modules.hunyuan.core.animation_merge import character_label

# Cards whose MESH output is a rigged character once they have run.
RIG_ACTION_TYPES = frozenset({'AUTO_RIG', 'ANIMATE'})


def _scene_objects(scene, names) -> list:
    objects = getattr(scene, "objects", None)
    found = (objects.get(name) for name in names) if objects is not None else ()
    return [obj for obj in found if obj is not None]


def _rig_of_objects(objects) -> tuple:
    """``(rig_job_id, skeleton, armature)`` from stamped objects."""
    for obj in objects:
        rig_job_id = find_rig_job_id(obj)
        if rig_job_id:
            armature = obj if obj.type == 'ARMATURE' else None
            if armature is None:
                try:
                    armature = obj.find_armature()
                except Exception:  # noqa: BLE001 — not every type has one
                    armature = None
            return rig_job_id, find_rig_skeleton(obj), armature
    return "", "", None


def source_rig_refusal(scene, node_id: str) -> str:
    """Why a graph node's output cannot feed Animate (an ``n_`` msgid), or "".

    Read-only (menus draw it). An Auto Rig / Animate card that has not
    produced its character yet qualifies (the run checks the result); one
    with a result, and an asset card, are judged by their objects' stamps.
    Any other card does not qualify (a generation re-imports fresh,
    unstamped objects).
    """
    from .node_graph import action_node_by_id, asset_node_by_id, mesh_source_object_names

    action = action_node_by_id(scene, node_id)
    if action is not None:
        if action.action_type not in RIG_ACTION_TYPES:
            return NOT_A_RIG
        objects = _scene_objects(scene, mesh_source_object_names(scene, node_id))
        return rig_refusal(*_rig_of_objects(objects)[:2]) if objects else ""
    asset = asset_node_by_id(scene, node_id)
    if asset is None:
        return NOT_A_RIG
    preview = getattr(asset, "preview_object", None)
    if preview is not None:
        objects = [preview]
    else:
        legacy = str(getattr(asset, "object_names", "") or "")
        objects = _scene_objects(scene, [name.strip() for name in legacy.split(",")])
    return rig_refusal(*_rig_of_objects(objects)[:2])


def source_carries_rig(scene, node_id: str) -> bool:
    """Whether a graph node's output is (or will be) a character Animate takes."""
    return not source_rig_refusal(scene, node_id)


def require_rig_source(scene, node_id: str) -> None:
    """``connect_nodes`` guard: an Animate input must be a rig that takes presets."""
    refusal = source_rig_refusal(scene, node_id)
    if refusal:
        raise ValueError(rpt_(refusal))


def rig_source(scene, node) -> tuple:
    """``(rig_job_id, skeleton, object_names, armature)`` feeding *node*.

    Read from the stamps on the connected objects (saved with the file).
    """
    from .node_graph import input_source_object_names

    names = input_source_object_names(scene, node)
    rig_job_id, skeleton, armature = _rig_of_objects(_scene_objects(scene, names))
    return rig_job_id, skeleton, names, armature


def _preset_parameter(node):
    return next(
        (p for p in node.parameters
         if p.name == ANIMATE_PRESETS_PARAM and p.parameter_type == 'ARRAY'),
        None,
    )


def refresh_preset_filter(scene, node) -> str:
    """Group the preset rows by skeleton and narrow the list to the rig's.

    Writes card data, so it runs from operators (the settings popup's invoke,
    the run), never from a draw. Returns the skeleton ("" = unknown: every
    preset stays listed).
    """
    parameter = _preset_parameter(node)
    if parameter is None:
        return ""
    skeleton = rig_source(scene, node)[1]
    for row in parameter.choices:
        if not row.group:
            row.group = preset_skeleton(row.value)
    if parameter.choice_filter != skeleton:
        parameter.choice_filter = skeleton
    return skeleton


def _node_result(scene_name: str, node_id: str):
    """Embed the animated character into the card once the clips merged."""
    def _on_merged(_job, character_names):
        import bpy

        scene = bpy.data.scenes.get(scene_name)
        node = None
        if scene is not None:
            from .node_graph import action_node_by_id

            node = action_node_by_id(scene, node_id)
        if node is not None:
            from .node_graph import create_asset_result

            create_asset_result(scene, node, ", ".join(character_names))

    return _on_merged


def run_animate_node(context, node):
    """Submit the card's presets for the connected rig. Returns ``(job, params)``."""
    from mixar.modules.common.generation_params import resolve_model_slug, resolve_service_key
    from mixar.modules.common.job_queue.constants import FEATURE_ANIMATE
    from .node_job_bridge import ensure_graph_listener
    from .node_schema import collect_node_params, node_model_slug, node_service_key

    scene = context.scene
    service_key = resolve_service_key(ANIMATION_CAPABILITY, node_service_key(node))
    if not service_key:
        raise ValueError(rpt_("Animate is unavailable in the generation catalog"))
    model = resolve_model_slug(service_key, node_model_slug(node))
    if not model:
        raise ValueError(rpt_("No enabled animation model is available"))

    rig_job_id, skeleton, names, armature = rig_source(scene, node)
    if not rig_job_id:
        raise ValueError(rpt_("Connect an Auto Rig result (a rigged character) to Animate"))
    refusal = rig_refusal(rig_job_id, skeleton)
    if refusal:
        raise ValueError(rpt_(refusal))
    refresh_preset_filter(scene, node)
    params = collect_node_params(node)
    presets = list(params.get(ANIMATE_PRESETS_PARAM) or ())
    parameter = _preset_parameter(node)
    choices = [{"value": row.value} for row in parameter.choices] if parameter else []
    error = preset_error(presets, choices, skeleton, translate=rpt_)
    if error:
        raise ValueError(error)

    rig_name = getattr(armature, "name", "")
    label = character_label(scene, armature) if armature is not None else names[0]
    ensure_graph_listener(FEATURE_ANIMATE)
    job = enqueue_retarget_job(
        rig_job_id=rig_job_id,
        service_key=service_key,
        model=model,
        params=params,
        label=label,
        rig_name=rig_name,
        graph_node_id=node.node_id,
        on_merged=_node_result(scene.name, node.node_id),
    )
    return job, params
