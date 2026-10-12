# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Help -> Save Support Bundle: logs, ledgers and checkpoint indexes, never
the checkpoint snapshots."""

import json
import os
import zipfile

from mixar.modules.space_mixie_chat.core import support_bundle


def test_the_bundle_ships_logs_ledgers_and_indexes_but_no_snapshots(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "mixar-client.log").write_text("2026-09-28T05:18:05.000Z WARNING x: hello\n")
    (logs / "mixar-client.log.1").write_text("older\n")
    (logs / "mixar-sandbox.log").write_text("sandbox\n")
    dossier = tmp_path / "scenes-dossier" / "sess-k"
    dossier.mkdir(parents=True)
    (dossier / "events.jsonl").write_text('{"event":"tab.new"}\n')
    checkpoints = tmp_path / "checkpoints" / "sess-k"
    checkpoints.mkdir(parents=True)
    (checkpoints / "index.json").write_text('{"checkpoints": []}')
    (checkpoints / "abc123.mixar").write_bytes(b"BLENDER" * 100)

    out = tmp_path / "bundle.zip"
    manifest = support_bundle.build_support_bundle(
        str(out), logs=str(logs), dossier=str(dossier.parent),
        checkpoints=str(checkpoints.parent),
        scenes=[{"name": "Kitchen", "objects": 3}], info={"mixar_version": "4.2.0"})
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        assert {"logs/mixar-client.log", "logs/mixar-client.log.1", "logs/mixar-sandbox.log",
                "scenes-dossier/sess-k/events.jsonl", "checkpoints/sess-k/index.json",
                "scenes.json", "app.json", "manifest.json"} <= names
        assert not any(name.endswith(".mixar") for name in names)
        assert json.loads(zf.read("scenes.json"))[0]["name"] == "Kitchen"
        assert json.loads(zf.read("app.json"))["mixar_version"] == "4.2.0"
    assert manifest["scenes"] == 1 and manifest["skipped"] == []


def test_an_oversized_file_is_listed_as_skipped(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "mixar-client.log").write_text("x" * 64)
    monkeypatch.setattr(support_bundle, "MAX_FILE_BYTES", 16)
    manifest = support_bundle.build_support_bundle(
        str(tmp_path / "b.zip"), logs=str(logs), dossier="", checkpoints="",
        scenes=[], info={})
    assert manifest["skipped"] == ["logs/mixar-client.log"]


def test_the_bundle_survives_missing_folders(tmp_path):
    out = tmp_path / "empty.zip"
    manifest = support_bundle.build_support_bundle(
        str(out), logs=str(tmp_path / "nope"), dossier="",
        checkpoints=str(tmp_path / "nada"), scenes=[], info={})
    assert manifest["files"] == ["scenes.json", "app.json"]
    assert os.path.getsize(out) > 0


def test_the_help_menu_entry_targets_the_operator():
    root = os.path.join(os.path.dirname(support_bundle.__file__), "..", "ui")
    with open(os.path.join(root, "menus", "support_bundle_menu.py"), encoding="utf-8") as f:
        menu = f.read()
    with open(os.path.join(root, "operators", "support_bundle_ops.py"), encoding="utf-8") as f:
        ops = f.read()
    assert "TOPBAR_MT_help.append" in menu and "TOPBAR_MT_help.remove" in menu
    assert 'bl_idname = "mixie_chat.save_support_bundle"' in ops
    assert '"mixie_chat.save_support_bundle"' in menu
