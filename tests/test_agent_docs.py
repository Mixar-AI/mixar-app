# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_agents_doc_delegates_to_canonical_claude_doc():
    # AGENTS.md is an internal-only file; it does not ship in the public
    # repo. Skip when absent so the test suite passes in both private
    # (where AGENTS.md exists) and public (where it does not).
    agents = ROOT / "AGENTS.md"
    if not agents.exists():
        pytest.skip("AGENTS.md not present (public build)")

    text = agents.read_text(encoding="utf-8")
    assert "CLAUDE.md" in text
    assert "Codex Sonnet" not in text
