# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent models catalog: the per-model projection behind the hosted picker.

`populate_from_payload` used to parse only `id`/`label` and throw the rest of
each model row away. The picker needs all six flags — and needs them in SERVER
ORDER, because providers arrive sorted by label and models in the admin-
configured `display_order`, and a client-side sort would silently disagree with
the admin dashboard.

The records live in a store PARALLEL to the enum tuples on purpose: Blender's
EnumProperty keeps the raw char* of every string handed to it (the reason
`_retire_current()` exists), so those tuples stay three elements wide.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.byok.core import model_suggestions


def _model(model_id, **overrides):
    row = {
        "id": model_id,
        "label": model_id.upper(),
        "platform_available": True,
        "byok_available": True,
        "supports_vision": True,
        "min_tier": None,
        "eligible": True,
        "thinking_levels": [],
    }
    row.update(overrides)
    return row


def _payload(*providers):
    return {"providers": list(providers)}


def _provider(pid, label, models):
    return {"id": pid, "label": label, "models": models}


def teardown_function(_function):
    model_suggestions.clear()


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------

def test_projection_keeps_every_per_model_field():
    model_suggestions.populate_from_payload(
        _payload(
            _provider("anthropic", "Anthropic", [
                _model(
                    "claude-sonnet-4-6",
                    label="Claude Sonnet 4.6",
                    min_tier="pro",
                    eligible=False,
                    supports_vision=False,
                    thinking_levels=["low", "medium", "high", "max"],
                )
            ])
        )
    )

    (row,) = model_suggestions.get_platform_models()

    assert row["provider_id"] == "anthropic"
    assert row["provider_label"] == "Anthropic"
    assert row["model_id"] == "claude-sonnet-4-6"
    assert row["model_label"] == "Claude Sonnet 4.6"
    assert row["platform_available"] is True
    assert row["byok_available"] is True
    assert row["supports_vision"] is False
    assert row["min_tier"] == "pro"
    assert row["eligible"] is False
    assert row["thinking_levels"] == ["low", "medium", "high", "max"]


def test_records_are_copies_so_a_reader_cannot_corrupt_the_cache():
    model_suggestions.populate_from_payload(
        _payload(_provider("openai", "OpenAI", [_model("gpt-5.5")]))
    )

    model_suggestions.get_platform_models()[0]["eligible"] = False

    assert model_suggestions.get_platform_models()[0]["eligible"] is True


def test_server_order_is_preserved_across_providers_and_models():
    """Never re-sorted: providers come sorted by label, models by display_order."""
    model_suggestions.populate_from_payload(
        _payload(
            _provider("anthropic", "Anthropic", [
                _model("z-first"), _model("a-second"),
            ]),
            _provider("openai", "OpenAI", [_model("gpt-5.5")]),
        )
    )

    assert [r["model_id"] for r in model_suggestions.get_platform_models()] == [
        "z-first", "a-second", "gpt-5.5",
    ]


def test_a_malformed_row_costs_one_row_not_the_list():
    model_suggestions.populate_from_payload(
        _payload(
            _provider("anthropic", "Anthropic", [
                _model("good-one"),
                "not-a-dict",
                {"label": "no id at all", "platform_available": True},
                _model("good-two"),
            ])
        )
    )

    assert [r["model_id"] for r in model_suggestions.get_platform_models()] == [
        "good-one", "good-two",
    ]


def test_thinking_levels_are_sanitised_not_trusted():
    model_suggestions.populate_from_payload(
        _payload(
            _provider("openai", "OpenAI", [
                _model("gpt-5.5", thinking_levels=["low", "", None, 7, "high"]),
                _model("gpt-5.5-mini", thinking_levels="high"),
            ])
        )
    )

    rows = model_suggestions.get_platform_models()
    assert rows[0]["thinking_levels"] == ["low", "high"]
    # A non-list is not a level list — degrade to "no thinking submenu".
    assert rows[1]["thinking_levels"] == []


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def test_platform_models_exclude_byok_only_rows():
    model_suggestions.populate_from_payload(
        _payload(
            _provider("anthropic", "Anthropic", [
                _model("hosted", platform_available=True),
                _model("byok-only", platform_available=False),
            ])
        )
    )

    assert [r["model_id"] for r in model_suggestions.get_platform_models()] == [
        "hosted"
    ]


def test_platform_available_fails_closed_when_the_field_is_absent():
    """Backend-authoritative lists never resurrect a client-side guess."""
    model_suggestions.populate_from_payload(
        _payload(_provider("anthropic", "Anthropic", [
            {"id": "legacy", "label": "Legacy"},
        ]))
    )

    assert model_suggestions.get_platform_models() == []


def test_ineligible_rows_are_kept_for_the_picker_to_grey_out():
    model_suggestions.populate_from_payload(
        _payload(_provider("anthropic", "Anthropic", [
            _model("locked", eligible=False, min_tier="studio"),
        ]))
    )

    (row,) = model_suggestions.get_platform_models()
    assert row["eligible"] is False
    assert row["min_tier"] == "studio"


def test_byok_dropdown_filters_to_byok_available_models():
    model_suggestions.populate_from_payload(
        _payload(_provider("anthropic", "Anthropic", [
            _model("with-key", byok_available=True),
            _model("platform-only", byok_available=False),
        ]))
    )

    assert [m[0] for m in model_suggestions.get_model_items("anthropic")] == [
        "with-key"
    ]
    # ...but the record store keeps both — the picker needs the other one.
    assert len(model_suggestions.get_platform_models()) == 2


def test_byok_available_fails_open_when_the_field_is_absent():
    """Advisory today: the BYOK save endpoints do not refuse a false flag, so an
    older backend that omits it must keep the pre-filter behaviour exactly."""
    model_suggestions.populate_from_payload(
        _payload(_provider("anthropic", "Anthropic", [
            {"id": "legacy", "label": "Legacy"},
        ]))
    )

    assert [m[0] for m in model_suggestions.get_model_items("anthropic")] == [
        "legacy"
    ]


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def test_an_authoritative_empty_catalog_replaces_the_records():
    model_suggestions.populate_from_payload(
        _payload(_provider("anthropic", "Anthropic", [_model("m")]))
    )
    model_suggestions.populate_from_payload(_payload())

    assert model_suggestions.get_platform_models() == []
    assert model_suggestions.is_loaded()


def test_clear_drops_the_records_with_everything_else():
    model_suggestions.populate_from_payload(
        _payload(_provider("anthropic", "Anthropic", [_model("m")]))
    )

    model_suggestions.clear()

    assert model_suggestions.get_platform_models() == []


def test_a_byok_only_populate_call_does_not_leave_stale_records():
    """`populate()` without records is the BYOK-only path; it must not leave the
    previous account's picker rows behind."""
    model_suggestions.populate_from_payload(
        _payload(_provider("anthropic", "Anthropic", [_model("m")]))
    )

    model_suggestions.populate(providers=[("x", "X", "X")], models={})

    assert model_suggestions.get_platform_models() == []
