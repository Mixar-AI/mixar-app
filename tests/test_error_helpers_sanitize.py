# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""sanitize_message must hide credential-shaped secrets, not keywords.

The old bare-word "token" rule replaced benign backend messages such as
"token limit exceeded" with "Something went wrong", hiding real failures
from artists.  Credential-shaped patterns (provider keys, JWTs, key=value
pairs, auth headers) are what actually need scrubbing.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.common.job_queue.core.error_helpers import sanitize_message

FALLBACK = "Something went wrong"


def test_benign_token_mentions_reach_users():
    assert sanitize_message("token limit exceeded") == "token limit exceeded"
    assert (
        sanitize_message("context length and token limit exceeded")
        == "context length and token limit exceeded"
    )


def test_provider_api_keys_are_scrubbed():
    assert sanitize_message("auth failed for sk-abcdefgh1234567890") == FALLBACK


def test_jwt_prefixes_are_scrubbed():
    jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjMifQ.sig"
    assert sanitize_message(f"unauthorized: {jwt}") == FALLBACK


def test_key_value_pairs_are_scrubbed():
    assert sanitize_message("bad request: api_key=sk_live_9m8n7b6v") == FALLBACK
    assert sanitize_message("bad request: api-key: abc123def456") == FALLBACK


def test_existing_keyword_rules_unchanged():
    assert sanitize_message("password hunter2") == FALLBACK
    assert sanitize_message("api key invalid") == FALLBACK


def test_long_messages_still_truncated():
    raw = "x" * 120
    assert sanitize_message(raw) == "x" * 77 + "…"
