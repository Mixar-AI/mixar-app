# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pure data model + builders for operation records (no bpy, no I/O)."""

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Optional

from ..constants import (
    CAT_MATERIAL, CAT_MODE, CAT_OBJECT, CAT_OTHER, CAT_QUERY, CAT_SCRIPT,
    CAT_SELECTION, CAT_TRANSFORM, CAT_UNDO, HISTORY_TOOLS, KIND_META,
    KIND_OPERATION, KIND_QUERY, MAX_LABEL_CHARS, READ_ONLY_TOOLS, SOURCE_AGENT,
    SOURCE_USER,
)

_EMPTY_DELTA = {"created": [], "modified": [], "deleted": []}
_EMPTY_AFFECTED = {"objects": [], "materials": [], "layers": []}

# operator bl_idname prefix -> category
_OP_PREFIX_CATEGORY = {
    "transform.": CAT_TRANSFORM,
    "object.delete": CAT_OBJECT,
    "object.select": CAT_SELECTION,
    "object.": CAT_OBJECT,
    "mesh.": CAT_OBJECT,
    "material.": CAT_MATERIAL,
    "ed.undo": CAT_UNDO,
    "ed.redo": CAT_UNDO,
}


@dataclass
class OperationRecord:
    source: str
    kind: str = KIND_OPERATION
    category: str = CAT_OTHER
    session_id: str = ""
    instance_id: str = ""
    request_id: Optional[str] = None
    intent_key: Optional[str] = None      # backend-only; null client-side (see CLAUDE notes)
    tool_name: Optional[str] = None
    op_idname: Optional[str] = None
    label: str = ""
    params: dict = field(default_factory=dict)
    success: bool = True
    error: Optional[str] = None
    affected: dict = field(default_factory=lambda: dict(_EMPTY_AFFECTED))
    scene_delta: dict = field(default_factory=lambda: dict(_EMPTY_DELTA))
    script_file: Optional[str] = None
    seq: int = 0           # assigned by the store on append
    id: str = ""
    ts: float = 0.0

    def finalize(self) -> "OperationRecord":
        if not self.id:
            self.id = uuid.uuid4().hex
        if not self.ts:
            self.ts = time.time()
        if self.label and len(self.label) > MAX_LABEL_CHARS:
            self.label = self.label[:MAX_LABEL_CHARS]
        return self

    def to_dict(self) -> dict:
        return asdict(self)


def derive_kind(tool_name: Optional[str]) -> str:
    if tool_name in HISTORY_TOOLS:
        return KIND_META
    if tool_name in READ_ONLY_TOOLS:
        return KIND_QUERY
    return KIND_OPERATION


def category_for_operator(op_idname: Optional[str]) -> str:
    if not op_idname:
        return CAT_OTHER
    name = op_idname.lower()
    for prefix, cat in _OP_PREFIX_CATEGORY.items():
        if name.startswith(prefix):
            return cat
    return CAT_OTHER


def _delta_from_result(result_dict: dict) -> dict:
    return {
        "created": list(result_dict.get("created_objects", []) or []),
        "modified": list(result_dict.get("modified_objects", []) or []),
        "deleted": list(result_dict.get("deleted_objects", []) or []),
    }


def build_agent_record(*, tool_name, result_dict, session_id,
                       instance_id="", request_id=None, script_present=True) -> OperationRecord:
    tn = tool_name or "unknown"
    kind = derive_kind(tn)
    delta = _delta_from_result(result_dict) if kind == KIND_OPERATION else dict(_EMPTY_DELTA)
    if kind != KIND_OPERATION:
        category = CAT_QUERY
    elif delta["created"] or delta["modified"] or delta["deleted"]:
        category = CAT_OBJECT
    else:
        category = CAT_SCRIPT
    affected = {
        "objects": sorted(set(delta["created"]) | set(delta["modified"]) | set(delta["deleted"])),
        "materials": [], "layers": [],
    }
    return OperationRecord(
        source=SOURCE_AGENT, kind=kind, category=category,
        session_id=session_id or "", instance_id=instance_id, request_id=request_id,
        tool_name=tn, label="Agent: {}".format(tn),
        success=bool(result_dict.get("success", False)),
        error=result_dict.get("error"), scene_delta=delta, affected=affected,
    ).finalize()


def build_manual_record(*, scene_delta, op_idname=None, label="", category=CAT_OTHER,
                        affected=None, session_id="", instance_id="") -> OperationRecord:
    return OperationRecord(
        source=SOURCE_USER, kind=KIND_OPERATION, category=category,
        session_id=session_id or "", instance_id=instance_id,
        op_idname=op_idname, label=label or (op_idname or "Manual edit"),
        affected=affected or dict(_EMPTY_AFFECTED),
        scene_delta=scene_delta or dict(_EMPTY_DELTA),
    ).finalize()
