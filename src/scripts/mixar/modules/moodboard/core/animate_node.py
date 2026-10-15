# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Animate card: preset animations retargeted onto a connected rig.

No export: the payload names the Auto Rig job (``rig_job_id``) the backend
already holds, read from the ``mixar_rig_job_id`` stamp on the connected
character (or the upstream Auto Rig card's own job id while its result is
still landing), plus the card's catalog params. The result's clips are
merged onto that same character (``hunyuan.core.animation_merge``), and the
card's result IS the character — armature and meshes — so another Animate
card or an export chains off it.
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
from mixar.modules.hunyuan.core.animate_presets import preset_error, preset_skeleton

# Cards whose MESH output is a rigged character once they have run.
RIG_ACTION_TYPES = frozenset({'AUTO_RIG', 'ANIMATE'})


def _scene_objects(scene, names) -> list:
    objects = getattr(scene, "objects", None)
    found = (objects.get(name) for name in names) if objects is not None else ()
    return [obj for obj in found if obj is not None]


def _rig_of_objects(objects) -> tuple:
    """``(rig_job_id, skeleton, armature_name)`` from stamped objects."""
    for obj in objects:
        rig_job_id = find_rig_job_id(obj)
        if rig_job_id:
            armature = obj if obj.type == 'ARMATURE' else None
            if armature is None:
                try:
                    armature = obj.find_armature()
                except Exception:  # noqa: BLE001 — not every type has one
                    armature = None
            return rig_job_id, find_rig_skeleton(obj), getattr(armature, "name", "")
    return "", "", ""


def source_carries_rig(scene, node_id: str) -> bool:
    """Whether a graph node's output is (or will be) a rigged character.

    Read-only (menus draw it): an Auto Rig / Animate card qualifies, any
    other card does not (a generation re-imports fresh, unstamped objects),
    and an asset card qualifies through the stamp on its object(s).
    """
    from .node_graph import action_node_by_id, asset_node_by_id

    action = action_node_by_id(scene, node_id)
    if action is not None:
        return action.action_type in RIG_ACTION_TYPES
    asset = asset_node_by_id(scene, node_id)
    if asset is None:
        return False
    preview = getattr(asset, "preview_object", None)
    if preview is not None:
        return bool(find_rig_job_id(preview))
    legacy = str(getattr(asset, "object_names", "") or "")
    names = [name.strip() for name in legacy.split(",") if name.strip()]
    return bool(_rig_of_objects(_scene_objects(scene, names))[0])


def require_rig_source(scene, node_id: str) -> None:
    """``connect_nodes`` guard: an Animate input must carry an Auto Rig job."""
    if not source_carries_rig(scene, node_id):
        raise ValueError(rpt_("Animate needs a rigged character: connect an Auto Rig result"))


def rig_source(scene, node) -> tuple:
    """``(rig_job_id, skeleton, object_names, armature_name)`` feeding *node*.

    The stamp on the connected objects wins (it is saved with the file); an
    upstream Auto Rig card that finished in this session supplies its job id
    while the stamp is still missing.
    """
    from .node_graph import action_node_by_id, input_source_object_names

    names = input_source_object_names(scene, node)
    rig_job_id, skeleton, armature = _rig_of_objects(_scene_objects(scene, names))
    if not rig_job_id:
        for link in getattr(scene, "mixie_moodboard_links", ()):
            if link.to_node_id != node.node_id:
                continue
            producer = action_node_by_id(scene, link.from_node_id)
            if producer is not None and producer.action_type == 'AUTO_RIG' and producer.job_id:
                rig_job_id = str(producer.job_id)
                break
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
    refresh_preset_filter(scene, node)
    params = collect_node_params(node)
    presets = list(params.get(ANIMATE_PRESETS_PARAM) or ())
    parameter = _preset_parameter(node)
    choices = [{"value": row.value} for row in parameter.choices] if parameter else []
    error = preset_error(presets, choices, skeleton)
    if error:
        raise ValueError(error)

    label = armature or names[0]
    ensure_graph_listener(FEATURE_ANIMATE)
    job = enqueue_retarget_job(
        rig_job_id=rig_job_id,
        service_key=service_key,
        model=model,
        params=params,
        label=label,
        rig_name=armature,
        graph_node_id=node.node_id,
        on_merged=_node_result(scene.name, node.node_id),
    )
    return job, params
