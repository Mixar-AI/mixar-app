# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""BYOK provider-dropdown regression coverage."""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.byok.core import model_suggestions


def test_client_provider_fallback_does_not_duplicate_catalog_entries():
    model_suggestions.populate(
        providers=[
            ("openrouter", "OpenRouter (admin label)", "From catalog"),
            ("openai", "OpenAI", "From catalog"),
        ],
        models={},
    )

    identifiers = [item[0] for item in model_suggestions.get_provider_items()]

    # OpenRouter is offered as a client-side fallback; when the catalog already
    # lists it, the fallback must not add a duplicate entry.
    assert identifiers.count("openrouter") == 1
    assert identifiers.count("openai") == 1
    model_suggestions.clear()


def test_openrouter_fallback_added_when_absent_from_catalog():
    model_suggestions.populate(
        providers=[("openai", "OpenAI", "From catalog")],
        models={},
    )

    identifiers = [item[0] for item in model_suggestions.get_provider_items()]

    # Always offered even when the backend catalog omits it.
    assert identifiers.count("openrouter") == 1
    model_suggestions.clear()
