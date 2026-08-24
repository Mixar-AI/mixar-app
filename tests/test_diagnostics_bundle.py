# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Support diagnostics dump is content-free (no tokens, paths, prompts)."""

import sys
from unittest.mock import MagicMock

for _name in ("keyring", "keyring.errors"):
    sys.modules.setdefault(_name, MagicMock(name=_name))

from mixar.modules.common.core import diagnostics as D


def test_build_diagnostics_has_session_fields(monkeypatch):
    monkeypatch.setattr(D, "_mixar_version", lambda: "1.2.3")
    monkeypatch.setattr(D, "_blender_version", lambda: "5.0.0")
    monkeypatch.setattr(D, "_signed_in", lambda: True)
    monkeypatch.setattr(D, "_catalog_version", lambda: "abc")
    monkeypatch.setattr(D, "_queue_snapshot", lambda: [])
    dump = D.build_diagnostics()
    assert dump["mixar_version"] == "1.2.3"
    assert dump["blender_version"] == "5.0.0"
    assert dump["signed_in"] is True
    assert dump["catalog_version"] == "abc"
    assert dump["queue"] == []
    text = D.diagnostics_text()
    assert "1.2.3" in text
    assert "token" not in text.lower() or "catalog_version" in text


def test_diagnostics_text_does_not_embed_secret_keys():
    text = D.diagnostics_text()
    for key in ("password", "authorization", "cookie"):
        assert key not in text.lower()
