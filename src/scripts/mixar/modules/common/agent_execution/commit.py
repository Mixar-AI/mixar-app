# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Typed foreground commit: ``append_collection``.

The only live write a v3 run makes to the user's scene. It appends (never
links) a collection from a worker-staged native artifact under a target
collection, at a foreground safe point, after every fence check, with the
journal recording PREPARED before and APPLIED after the short publish. No
model-authored Python runs here.

Main thread only. ``bpy_module`` is injectable for tests.
"""

from __future__ import annotations

import time
from typing import Optional

from mixar.config.logging_config import get_logger

from . import bindings, document
from .artifacts import ArtifactError, resolve
from .journal import APPLIED, PREPARED, RUNNING, UNKNOWN, get_journal
from .placement import PlacementError, apply_placement, is_identity, parse_placement, top_level_objects

logger = get_logger(__name__)

DEFAULT_TARGET_COLLECTION = "Mixie Agent"
# Modes in which a stroke may be mid-way; appending then risks interleaving
# with a paint/sculpt operator's undo step. Edit mode is fine.
_DEFERRED_MODES = ("SCULPT", "PAINT_TEXTURE", "PAINT_VERTEX", "PAINT_WEIGHT", "PAINT_GPENCIL",
                   "SCULPT_GPENCIL", "SCULPT_CURVES")


def _err(error_type: str, message: str, **extra) -> dict:
    out = {"success": False, "error": message, "error_type": error_type}
    out.update(extra)
    return out


def _instance_id(bpy) -> str:
    try:
        wm = bpy.context.window_manager
        return str(getattr(wm, "mixie_instance_id", "") or "")
    except Exception:
        return ""


def _foreground_busy(bpy) -> Optional[str]:
    try:
        mode = str(getattr(bpy.context, "mode", "OBJECT") or "OBJECT")
    except Exception:
        mode = "OBJECT"
    if mode in _DEFERRED_MODES:
        return f"foreground is in {mode} mode"
    try:
        if bool(getattr(bpy.context.window_manager, "is_interface_locked", False)):
            return "interface is locked by a running job"
    except Exception:
        pass
    return None


class _ViewState:
    """Capture and restore selection / active object / camera around the publish."""

    def __init__(self, bpy):
        self.bpy = bpy
        try:
            self.active = bpy.context.view_layer.objects.active
            self.selected = [o for o in bpy.context.selected_objects]
            self.camera = bpy.context.scene.camera
        except Exception:
            self.active, self.selected, self.camera = None, [], None

    def restore(self) -> None:
        bpy = self.bpy
        try:
            for o in bpy.context.selected_objects:
                o.select_set(False)
            for o in self.selected:
                try:
                    o.select_set(True)
                except Exception:
                    pass
            bpy.context.view_layer.objects.active = self.active
            if bpy.context.scene.camera is not self.camera:
                bpy.context.scene.camera = self.camera
        except Exception:
            logger.debug("view state restore skipped", exc_info=True)


def _target_collection(bpy, name: str):
    scene = bpy.context.scene
    existing = scene.collection.children.get(name)
    if existing is not None:
        return existing
    coll = bpy.data.collections.get(name)
    if coll is None:
        coll = bpy.data.collections.new(name)
    scene.collection.children.link(coll)
    return coll


def append_collection(params: dict, *, bpy_module=None, journal=None) -> dict:
    if bpy_module is None:
        import bpy as bpy_module
    bpy = bpy_module
    journal = journal or get_journal()

    run_id = str(params.get("run_id") or "")
    task_id = str(params.get("task_id") or "")
    generation = bindings._int(params.get("generation"))
    fence = bindings._int(params.get("fence_token"))
    operation_id = str(params.get("operation_id") or "")
    payload_hash = str(params.get("payload_hash") or "")
    artifact_id = params.get("artifact_id")
    content_hash = str(params.get("content_hash") or "")
    collection_name = str(params.get("collection_name") or "")
    target_name = str(params.get("target_collection") or DEFAULT_TARGET_COLLECTION)
    if params.get("op", "append_collection") != "append_collection":
        return _err("invalid_params", f"unsupported op {params.get('op')!r}")
    if not (run_id and task_id and operation_id and payload_hash and collection_name):
        return _err("invalid_params", "commit requires run_id, task_id, operation_id, payload_hash, collection_name")
    # Placement is validated up front: a bad value must never half-apply.
    try:
        placement = parse_placement(params.get("placement"))
    except PlacementError as exc:
        return _err("invalid_params", f"placement: {exc}")

    # 1. ownership / epoch / fence
    refused = bindings.check_commit_allowed(run_id, params.get("turn_epoch"), task_id, fence, journal)
    if refused is not None:
        return _err(refused[0], refused[1])

    # 2. journal: idempotent replay
    existing = journal.op_get(operation_id)
    if existing is not None:
        if existing["payload_hash"] != payload_hash:
            return _err("payload_mismatch", "operation id already used with a different payload")
        if existing["state"] == APPLIED:
            return {"success": True, "state": APPLIED, "receipt": existing["receipt"], "replayed": True}
        if existing["state"] == RUNNING:
            return _err("deferred", "operation is in progress", state=RUNNING)
        if existing["state"] == UNKNOWN:
            return _err("unknown", "operation outcome is unknown; inspect before retrying", state=UNKNOWN)

    # 3. artifact
    try:
        path = resolve(_instance_id(bpy), artifact_id, content_hash or None)
    except ArtifactError as exc:
        return _err(exc.error_type, str(exc))

    # 4. safe point
    busy = _foreground_busy(bpy)
    if busy:
        return _err("deferred", busy)

    identity = document.document_identity(bpy=bpy)
    journal.op_prepare(
        operation_id, run_id=run_id, task_id=task_id, generation=generation, fence=fence,
        payload_hash=payload_hash, document_id=identity["document_id"],
        document_epoch=identity["document_epoch"], artifact_id=artifact_id,
    )
    journal.op_set_state(operation_id, RUNNING)

    # 5. the short publish — no yielding between the final check and the link
    view = _ViewState(bpy)
    created: list[str] = []
    try:
        with document.commit_scope():
            with bpy.data.libraries.load(path, link=False) as (data_from, data_to):
                if collection_name not in list(data_from.collections):
                    raise ArtifactError("artifact_missing",
                                        f"collection {collection_name!r} not in artifact")
                data_to.collections = [collection_name]
            appended = data_to.collections[0]
            if appended is None:
                raise ArtifactError("artifact_missing", "append produced no collection")
            target = _target_collection(bpy, target_name)
            if appended.name not in [c.name for c in target.children]:
                target.children.link(appended)
            created = [o.name for o in appended.all_objects]
            applied_name = appended.name
            # Placement rides in the same publish window: the plan's location,
            # world-Z rotation and uniform scale for the top-level objects only
            # (children follow their parents).
            placement_applied = False
            if not is_identity(placement):
                apply_placement(top_level_objects(appended), placement)
                placement_applied = True
    except ArtifactError as exc:
        journal.op_set_state(operation_id, PREPARED)
        return _err(exc.error_type, str(exc))
    except Exception as exc:  # noqa: BLE001 — partial effect possible
        logger.error("append_collection failed mid-publish: %s", exc, exc_info=True)
        journal.op_set_state(operation_id, UNKNOWN, {"error": str(exc)})
        return _err("unknown", f"append failed mid-publish: {exc}", state=UNKNOWN)
    finally:
        view.restore()

    receipt = {
        "created_object_names": created,
        "collection_name": applied_name,
        "target_collection": target_name,
        "document_epoch": document.document_epoch(),
        "applied_at": time.time(),
        "placement_applied": placement_applied,
        "placement": placement,
    }
    journal.op_set_state(operation_id, APPLIED, receipt)
    _record_history(bpy, params, receipt)
    return {"success": True, "state": APPLIED, "receipt": receipt}


def _record_history(bpy, params: dict, receipt: dict) -> None:
    """Attribute the publish to the agent in operation history (fail-soft)."""
    try:
        from mixar.modules.operation_history.core import store as _op_store
        from mixar.modules.operation_history.core.record import build_agent_record
        from mixar.modules.operation_history.core.scene_key import get_scene_history_id

        scene = bpy.context.scene
        _op_store.append_operation(
            build_agent_record(
                tool_name="agent_commit",
                result_dict={"success": True, "created_objects": receipt["created_object_names"]},
                session_id=get_scene_history_id(scene),
                instance_id=_instance_id(bpy),
                request_id=str(params.get("operation_id") or ""),
            )
        )
    except Exception:
        logger.debug("agent_commit history record skipped", exc_info=True)
