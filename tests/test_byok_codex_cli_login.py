# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Codex (ChatGPT sub): only the CLI login's three sign-in tokens leave the
computer — never the whole auth.json, and never through the clipboard."""

import base64
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.byok.core import codex_cli_login


def _jwt(claims: dict) -> str:
    def seg(b: bytes) -> str:
        return base64.urlsafe_b64encode(b).decode().rstrip("=")
    return f"{seg(b'{}')}.{seg(json.dumps(claims).encode())}.sig"


def _auth_json(**tokens):
    return json.dumps({
        "OPENAI_API_KEY": "sk-should-never-leave",
        "last_refresh": "2026-10-01T00:00:00Z",
        "tokens": {
            "id_token": _jwt({"email": "u@x.com",
                              "https://api.openai.com/auth": {"chatgpt_account_id": "acc-jwt"}}),
            "access_token": "access-jwt",
            "refresh_token": "refresh-1",
            "account_id": "acc-1",
            **tokens,
        },
    })


def test_only_the_three_token_fields_are_kept():
    bundle = json.loads(codex_cli_login.minimal_bundle(_auth_json()))
    assert bundle == {"refresh_token": "refresh-1", "access_token": "access-jwt",
                      "account_id": "acc-1"}


def test_account_id_is_derived_locally_without_sending_the_id_token():
    text = codex_cli_login.minimal_bundle(_auth_json(account_id=""))
    assert json.loads(text)["account_id"] == "acc-jwt"
    assert "id_token" not in text and "u@x.com" not in text
    assert "sk-should-never-leave" not in text


@pytest.mark.parametrize("text", [
    "not json",
    json.dumps({"OPENAI_API_KEY": "sk-x", "tokens": None}),
    _auth_json(refresh_token=""),
])
def test_no_chatgpt_login_is_refused(text):
    with pytest.raises(ValueError):
        codex_cli_login.minimal_bundle(text)


def test_reads_codex_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    with pytest.raises(ValueError) as e:
        codex_cli_login.read_minimal_bundle()
    assert str(e.value) == codex_cli_login.MSG_NOT_FOUND
    (tmp_path / "auth.json").write_text(_auth_json(), encoding="utf-8")
    assert json.loads(codex_cli_login.read_minimal_bundle())["refresh_token"] == "refresh-1"


def test_no_clipboard_or_whole_file_path_remains():
    ops = SCRIPTS / "mixar/modules/byok/ui/operators"
    source = "".join(p.read_text(encoding="utf-8") for p in ops.glob("*.py"))
    assert "wm.clipboard" not in source
    assert "codex_paste" not in source and "codex_load_file" not in source
    assert "byok_form_codex_bundle')" not in source  # never drawn as a field
