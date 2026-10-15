# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Retarget preset rules shared by the Animate card and the agent operator."""

import sys
from types import SimpleNamespace as NS

from mixar.modules.common import generation_params
from mixar.modules.hunyuan.core import animate_presets as presets

CHOICES = [
    {"value": "preset:biped:walk", "label": "Walk"},
    {"value": "preset:biped:wave_goodbye_01", "label": "Wave Goodbye 01"},
    {"value": "preset:quadruped:walk", "label": "Quadruped Walk"},
    {"value": "preset:serpentine:march", "label": "Serpentine March"},
]


def test_a_presets_skeleton_is_its_second_segment():
    assert presets.preset_skeleton("preset:biped:walk") == "biped"
    assert presets.preset_skeleton("preset:Quadruped:walk") == "quadruped"
    assert presets.preset_skeleton("preset:walk") == ""  # the retired v2.5 humanoid shape
    assert presets.preset_skeleton("") == ""
    assert presets.clip_name("preset:biped:wave_goodbye_01") == "wave_goodbye_01"


def test_the_agent_list_is_split_trimmed_and_deduplicated():
    assert presets.parse_preset_list(" preset:biped:walk, preset:biped:idle ,,preset:biped:walk") == [
        "preset:biped:walk", "preset:biped:idle"]
    assert presets.parse_preset_list("") == []


def test_preset_errors_name_the_problem():
    assert "at least one" in presets.preset_error([], CHOICES, "biped")
    assert "Unknown animation preset(s): preset:biped:fly" in presets.preset_error(
        ["preset:biped:fly"], CHOICES, "biped")
    assert "preset:quadruped:walk: not for a biped rig — pick biped presets" == presets.preset_error(
        ["preset:biped:walk", "preset:quadruped:walk"], CHOICES, "biped")
    # Unknown rig skeleton or unknown catalog: nothing to check against.
    assert presets.preset_error(["preset:quadruped:walk"], CHOICES, "") == ""
    assert presets.preset_error(["preset:anything:x"], [], "") == ""


def test_presets_for_skeleton_keeps_the_rigs_and_the_shapeless():
    assert [c["value"] for c in presets.presets_for_skeleton(CHOICES, "quadruped")] == [
        "preset:quadruped:walk"]
    assert presets.presets_for_skeleton(CHOICES, "") == CHOICES


def test_the_retarget_catalog_reads_the_animation_capability(monkeypatch):
    model = {"slug": "tripo_retarget_v2_5", "parameters": {
        "animations": {"type": "array", "choices": CHOICES},
        "animate_in_place": {"type": "boolean"},
    }}
    fake = NS(
        get_services=lambda capability, surface=None: (
            [{"key": "tripo_retarget"}] if capability == "animation" else []),
        get_model=lambda service, slug: model if slug == model["slug"] else None,
    )
    monkeypatch.setitem(sys.modules, "mixar.bootstrap.generation_catalog_cache", fake)
    monkeypatch.setattr(generation_params, "catalog_default_model", lambda key: model["slug"])
    service, slug, choices = presets.retarget_catalog()
    assert (service, slug) == ("tripo_retarget", "tripo_retarget_v2_5")
    assert [c["value"] for c in choices] == [c["value"] for c in CHOICES]

    monkeypatch.setattr(fake, "get_services", lambda capability, surface=None: [])
    assert presets.retarget_catalog() == ("", "", [])
