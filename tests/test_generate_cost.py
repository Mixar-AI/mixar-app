# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Generate-button billed credit cost (catalog + compact formatting)."""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

for _name in ("keyring", "keyring.errors"):
    sys.modules.setdefault(_name, MagicMock(name=_name))

from mixar.bootstrap.generation_catalog.queries import GenerationCatalogQueries

_PATH = (
    Path(__file__).resolve().parents[1]
    / "src/scripts/mixar/modules/common/job_queue/core/generate_cost.py"
)
_spec = importlib.util.spec_from_file_location("generate_cost", _PATH)
generate_cost = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(generate_cost)
format_credits_compact = generate_cost.format_credits_compact
generate_button_text = generate_cost.generate_button_text
reset_estimate_state = generate_cost.reset_estimate_state


def _queries(payload):
    return GenerationCatalogQueries(lambda: payload)


def test_format_credits_compact():
    assert format_credits_compact(12) == "12"
    assert format_credits_compact(12.0) == "12"
    assert format_credits_compact(1500) == "1.5K"
    assert format_credits_compact(None) == ""
    assert format_credits_compact(-1) == ""


def test_resolve_generate_cost_prefers_model_then_service_then_map():
    payload = {
        "capabilities": [{
            "key": "image_gen",
            "services": [{
                "key": "image_gen",
                "feature_key": "image_generation",
                "credit_cost": 10,
                "models": [
                    {"slug": "flash", "credit_cost": 14, "is_default": True},
                ],
            }],
        }],
        "credit_costs": {"image_generation": 10},
    }
    queries = _queries(payload)
    assert queries.resolve_generate_cost("image_gen", "flash") == 14
    assert queries.resolve_generate_cost("image_gen") == 10
    assert queries.resolve_generate_cost(feature_key="image_generation") == 10
    assert queries.resolve_generate_cost("missing") is None
    assert queries.resolve_generate_cost("image_gen", "flash", "image_generation") == 14


def test_generate_button_text_uses_catalog_cost(monkeypatch):
    reset_estimate_state()
    monkeypatch.setattr(
        generate_cost, "catalog_cost",
        lambda service_key="", model_slug="", feature_key="": 12,
    )
    assert generate_button_text("image_gen", "flash") == "Generate · 12"
    monkeypatch.setattr(
        generate_cost, "catalog_cost",
        lambda service_key="", model_slug="", feature_key="": None,
    )
    assert generate_button_text("image_gen", "flash") == "Generate"
