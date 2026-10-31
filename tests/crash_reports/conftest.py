# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fixtures for crash-reporting tests. The crash files under ``fixtures/`` are
scrubbed copies of real Mixar crash logs (prompts, paths and ids replaced with
synthetic ones) plus synthetic Windows / Linux logs in Blender's format."""

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_text():
    def read(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")
    return read
