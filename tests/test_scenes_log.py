# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import os
import sys

import pytest


_SRC_SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "scripts"))
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)


@pytest.fixture
def scenes_log():
    from mixar.modules.common import scenes_log as module  # noqa: PLC0415
    return module


class _Scene:
    def __init__(self, name, sid):
        self.name = name
        self.mixie_session_id = sid


def test_slog_writes_client_record_under_session(tmp_path, monkeypatch, scenes_log):
    monkeypatch.setenv("MIXAR_SCENES_DOSSIER_DIR", str(tmp_path))
    scenes_log.slog("route.pin", _Scene("Kitchen", "sess-a"), target="Kitchen", was="Scene")
    rows = [json.loads(l) for l in (tmp_path / "sess-a" / "events.jsonl").read_text().splitlines()]
    assert rows == [dict(rows[0], **{"side": "client", "event": "route.pin",
                                     "session_id": "sess-a", "scene": "Kitchen",
                                     "target": "Kitchen", "was": "Scene"})]


def test_slog_unrouted_and_disabled(tmp_path, monkeypatch, scenes_log):
    monkeypatch.setenv("MIXAR_SCENES_DOSSIER_DIR", str(tmp_path))
    scenes_log.slog("route.reject", None, key="agent:x")
    assert (tmp_path / "_unrouted" / "events.jsonl").exists()
    monkeypatch.setenv("MIXAR_SCENES_DOSSIER_DIR", "0")
    scenes_log.slog("route.reject", _Scene("S", "sess-b"))
    assert not (tmp_path / "sess-b").exists()


def test_slog_never_raises(tmp_path, monkeypatch, scenes_log):
    bad = tmp_path / "file"
    bad.write_text("x")
    monkeypatch.setenv("MIXAR_SCENES_DOSSIER_DIR", str(bad))
    scenes_log.slog("sweep.lane", _Scene("L", "../escape"), parent="sess-a")
