# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The 3D targets' readiness block: the export lane's preflight (the checks
the agent runs before an export) and its "Fix" (``repair_export``), run only
when the user asks — a preflight walks every material's node tree, so it
never runs on a draw or a tile click."""

from __future__ import annotations

import uuid

from mixar.modules.common.i18n import n_

from .. import constants as C
from . import spec as card_spec
from . import state

LABELS = {
    "transforms": n_("Rotation and scale not applied"),
    "modifiers": n_("Modifiers not applied"),
    "packed_images": n_("Material images not packed"),
    "mixar_bakes": n_("Paint layers not baked"),
}
NAMES_SHOWN = 3


def key(p) -> tuple:
    return (p.target, card_spec.model_format(p), p.scope)


def _store(p, report: dict) -> dict:
    state.set_readiness(key(p), report)
    return report


def check(p) -> dict:
    from mixar.modules.space_mixie_chat.core.agent_export import inspect_export
    return _store(p, inspect_export(card_spec.model_spec(p, "check")))


def fix(p) -> dict:
    """Repair the failing meshes in the scene, then report again."""
    from mixar.modules.space_mixie_chat.core.agent_export import scrub_error
    from mixar.modules.space_mixie_chat.core.export_preflight import repair_export
    try:
        report = repair_export(C.REPAIR_SESSION, uuid.uuid4().hex, "export_card",
                               card_spec.model_spec(p, "check"))
    except Exception as exc:  # noqa: BLE001 - shown on the card
        report = {"success": False, "ready": False, "error": scrub_error(exc)}
    return _store(p, report)


def failures(report: dict) -> list[tuple[str, int, list[str]]]:
    """``(label msgid, mesh count, first names)`` per failing, used check."""
    out = []
    for check_key, item in (report.get("checks") or {}).items():
        if item.get("skipped") or not item.get("failed"):
            continue
        names = list(item.get("failed_meshes") or [])
        out.append((LABELS.get(check_key, check_key), int(item["failed"]), names[:NAMES_SHOWN]))
    return out
