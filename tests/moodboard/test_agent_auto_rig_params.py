# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent auto-rig params are gated by the rig model's catalog schema: a key
the model does not declare is dropped, a declared enum is validated against
the schema, and only an unknown catalog keeps the legacy Tripo behaviour."""

import ast
from pathlib import Path

import pytest

from mixar.bootstrap import generation_catalog_cache as GCC
from mixar.modules.moodboard.core import auto_rig_params as ARP

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "src/scripts/mixar/modules/moodboard/ui/operators/agent_auto_rig_ops.py"

TRIPO = {"slug": "tripo", "parameters": {
    "rig_type": {"type": "string", "enum": ["auto", "biped", "quadruped"]},
    # Tripo Auto Rig 3.0's Skeleton param: six bone namings (backend catalog).
    "spec": {"type": "string", "choices": [
        {"value": "tripo", "label": "Tripo native bone naming"},
        {"value": "mixamo", "label": "Mixamo-compatible bone naming"},
        {"value": "actorcore", "label": "ActorCore humanoid bone naming"},
        {"value": "unity", "label": "Unity Humanoid bone naming"},
        {"value": "unreal", "label": "Unreal Mannequin bone naming"},
        {"value": "vrm", "label": "VRM 1.0 humanoid bone naming"},
    ]},
}}
MESHY = {"slug": "meshy", "parameters": {"height_meters": {"type": "number"}}}


@pytest.fixture
def catalog(monkeypatch):
    models = {}
    monkeypatch.setattr(GCC, "get_model", lambda service, slug: models.get(slug))
    return models


def test_tripo_schema_sends_declared_enum_values(catalog):
    catalog["tripo"] = TRIPO
    params, reason = ARP.build_rig_params("tripo", "Biped", "mixamo", 1.8)
    assert reason == ""
    assert params == {"rig_type": "biped", "spec": "mixamo"}

    params, reason = ARP.build_rig_params("tripo", "hexapod", "tripo", 0)
    assert params is None and "rig_type" in reason and "quadruped" in reason


@pytest.mark.parametrize("spec", ["actorcore", "unity", "Unreal", "vrm"])
def test_every_catalog_bone_naming_is_accepted(catalog, spec):
    catalog["tripo"] = TRIPO
    params, reason = ARP.build_rig_params("tripo", "biped", spec, 0)
    assert reason == "" and params == {"rig_type": "biped", "spec": spec.lower()}
    params, reason = ARP.build_rig_params("tripo", "biped", "others", 0)
    assert params is None and "spec" in reason


def test_meshy_schema_drops_undeclared_rig_type_and_spec(catalog):
    catalog["meshy"] = MESHY
    params, reason = ARP.build_rig_params("meshy", "auto", "tripo", 1.75)
    assert reason == ""
    assert params == {"height_meters": 1.75}
    assert ARP.build_rig_params("meshy", "auto", "tripo", 0)[0] == {}


def test_no_catalog_keeps_the_legacy_tripo_behaviour(catalog):
    params, reason = ARP.build_rig_params("tripo", "", "", 1.8)
    assert reason == ""
    assert params == {"rig_type": "auto", "spec": "tripo"}  # height never sent
    assert ARP.build_rig_params("tripo", "biped", "unreal", 0)[0] == {
        "rig_type": "biped", "spec": "unreal"}
    params, reason = ARP.build_rig_params("tripo", "biped", "others", 0)
    assert params is None and "spec" in reason


def test_the_operator_builds_its_payload_through_the_gate():
    source = OPS.read_text(encoding="utf-8")
    tree = ast.parse(source)
    execute = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "execute"
    )
    body = ast.unparse(execute)
    assert "build_rig_params(" in body
    assert "'rig_type': rig_type" not in body
    assert "_RIG_TYPES" not in source and "_SPECS" not in source
