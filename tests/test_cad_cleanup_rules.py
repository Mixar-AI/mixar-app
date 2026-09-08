# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Regression corpus for CAD evidence rules; no Blender runtime is required."""

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "src/scripts/mixar/modules/common/cad_cleanup/core/rules.py"
SPEC = importlib.util.spec_from_file_location("cad_rules_under_test", MODULE)
rules = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rules)
CASES = json.loads(Path(__file__).with_name("cad_cleanup_cases.json").read_text())


@pytest.mark.parametrize("case", CASES["classification"], ids=lambda c: c["name"])
def test_known_name_misclassifications(case):
    result = rules.classify({"name": case["name"], "dimensions": [1, 1, 1]})
    assert result["category"].startswith("_SYS_" + case["system"] + "_"), result
    assert result["confidence"] == "high"
    assert result["evidence"]


@pytest.mark.parametrize("name,category", [
    ("FR DOOR OUTER PANEL", "_VIZ_FR_DOOR_OUTER_PANEL"),
    ("FR DOOR OTR PANEL", "_VIZ_FR_DOOR_OUTER_PANEL"),
    ("FR DOOR WINDOW GLASS", "_VIZ_FR_DOOR_GLASS"),
    ("RR DOOR INR PANEL", "_VIZ_RR_DOOR_INNER_PANEL"),
    ("DOOR OUTER PANEL", "_VIZ_DOOR_OUTER_PANEL"),
    ("FR DOOR DESCRIPTION PLATE", "_VIZ_FR_DOOR_MAIN"),
    ("Surface Assembly\\BRKT-ENGINE", "_SYS_ENGINE_REINF_BRKT"),
    ("Engine Assembly/STEERING WHEEL", "_SYS_STEERING_MAIN"),
])
def test_descriptor_scope_and_door_aliases(name, category):
    assert rules.classify({"name": name})["category"] == category


@pytest.mark.parametrize("name", ["ENGINE BRAKE", "FR RR DOOR OUTER PANEL",
                                 "STEERING WHEEL SHOCK ABS", "HEADLINER LAMP",
                                 "STEERING WHEEL SENSOR", "WHEELHOUSE BRAKE PIPE"])
def test_conflicting_systems_require_review(name):
    result = rules.classify({"name": name})
    assert result["category"] == "_REVIEW_CONFLICT", result
    assert result["confidence"] == "low"


@pytest.mark.parametrize("name", ["", "Body", "Solid12", "Product123", "未知零件"])
def test_missing_evidence_is_not_identified(name):
    result = rules.classify({"name": name})
    assert result["category"].startswith("_REVIEW_"), result
    assert result["confidence"] == "low"


@pytest.mark.parametrize("name", ["Copy (1) of L0638042_FOAM_PAD",
                                 "801529857R--A_002_NULL_FROZEN",
                                 "801529858R--A_002_FR DOOR OUTER PANEL_FROZEN"])
def test_real_part_protection_survives_descriptor_quality(name):
    assert rules.parse_name(name)["protected"] is True


@pytest.mark.parametrize("case", CASES["preserve"], ids=lambda c: c["name"])
def test_name_rules_never_destroy_uncertain_parts(case):
    record = {"name": case["name"], "dimensions": [2, 1, 0.001]}
    for secondary in (False, True):
        result = rules.cull_evidence(record, secondary=secondary)
        assert result is None or result["category"].startswith("_REVIEW_"), result
    assert not rules.classify(record)["category"].startswith("_Cull_"), case


def test_parent_surface_word_does_not_supply_cull_evidence():
    assert rules.cull_evidence({"name": "Surface Assembly\\BRKT-ENGINE"}) is None


@pytest.mark.parametrize("name", ["SHOCK ABS", "ENGINE BLOCK", "FR DOOR OUTER PANEL"])
def test_case_and_separator_normalization(name):
    expected = rules.classify({"name": name})["category"]
    for spelling in (name.lower(), name.replace(" ", "_"), name.replace(" ", "-")):
        assert rules.classify({"name": spelling})["category"] == expected


def test_no_dimension_only_sensor_reclassification():
    large = rules.classify({"name": "DISTANCE SENSOR", "dimensions": [2, 1, 1]})
    small = rules.classify({"name": "DISTANCE SENSOR", "dimensions": [0.01] * 3})
    assert large["category"] == small["category"] == "_SYS_ELECTRICAL_MAIN"
