# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene forensics: the log file, the scene datablock audit, the tab context
on the chat payload, and the support bundle."""

import json
import logging
import os
import zipfile
from types import SimpleNamespace

import pytest
from _open_run_support import _scene, live_bpy  # noqa: F401

from mixar.config import logging_config
from mixar.modules.space_mixie_chat.core import chat_payloads, scene_identity, support_bundle


# ---------------------------------------------------------------------------
# Log file
# ---------------------------------------------------------------------------


@pytest.fixture
def log_folder(tmp_path, monkeypatch):
    folder = tmp_path / "logs"
    monkeypatch.setenv("MIXAR_CLIENT_LOG_DIR", str(folder))
    logging_config.reset_file_handler()
    yield folder
    logging_config.reset_file_handler()


def _read(folder):
    path = folder / logging_config.LOG_FILENAME
    for handler in logging.getLogger().handlers:
        handler.flush()
    handler = logging_config.get_file_handler()
    if handler is not None:
        handler.flush()
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_warnings_reach_the_file_even_when_the_console_is_at_error(log_folder):
    logger = logging_config.get_logger("mixar.forensics.test_a", level=logging.ERROR)
    logger.warning("tab went missing")
    logger.info("chatter")
    text = _read(log_folder)
    assert "tab went missing" in text
    assert "chatter" not in text
    line = next(ln for ln in text.splitlines() if "tab went missing" in ln)
    stamp = line.split(" ")[0]
    assert stamp.endswith("Z") and "T" in stamp and len(stamp) == 24   # 2026-09-28T05:18:05.123Z
    assert "mixar.forensics.test_a" in line


def test_the_scenes_ledger_floor_lets_info_through_to_the_file_only(log_folder, capsys):
    logger = logging_config.get_logger("mixar.forensics.test_b", level=logging.ERROR,
                                       file_floor=logging.INFO)
    logger.info("[SCENES] event=scene.added scene=Kitchen.001")
    assert "scene.added" in _read(log_folder)
    assert "scene.added" not in capsys.readouterr().out


def test_file_logging_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setenv("MIXAR_CLIENT_LOG_DIR", "0")
    logging_config.reset_file_handler()
    try:
        assert logging_config.get_file_handler() is None
        logger = logging_config.get_logger("mixar.forensics.test_c", level=logging.ERROR)
        logger.warning("nowhere")          # no handler, no error
    finally:
        logging_config.reset_file_handler()


# ---------------------------------------------------------------------------
# Scene datablock audit
# ---------------------------------------------------------------------------


class _AuditScene(SimpleNamespace):
    def keys(self):
        return list(self._keys)


def _audit_scene(name, session_id="", objects=0, world="World", keys=()):
    base = _scene(name, session_id=session_id)
    scene = _AuditScene(**base.__dict__)
    scene.objects = [object()] * objects
    scene.world = SimpleNamespace(name=world) if world else None
    scene.camera = None
    scene.users = 1
    scene._keys = list(keys)
    return scene


@pytest.fixture
def audit(live_bpy, monkeypatch):
    monkeypatch.setenv("MIXAR_SCENES_DOSSIER_DIR", "0")
    # Other suites swap sys.modules["bpy"] mid-session; the module holds the
    # bpy it imported, so point it at the one this test populates.
    monkeypatch.setattr(scene_identity, "bpy", live_bpy)
    events = []
    monkeypatch.setattr(scene_identity, "slog",
                        lambda event, scene=None, **fields: events.append((event, scene, fields)))
    monkeypatch.setattr(scene_identity, "_recent_operators", lambda: ["scene.new"])
    monkeypatch.setattr(scene_identity, "_window_scene_name", lambda: "Kitchen")
    scene_identity._known_scene_names = set()
    return live_bpy, events


def test_a_new_scene_is_logged_with_its_fingerprint_and_the_last_operator(audit):
    bpy, events = audit
    kitchen = _audit_scene("Kitchen", "sess-k", objects=12, keys=["mixar_tab_order"])
    bpy.data.scenes.append(kitchen)
    scene_identity.audit_scenes()             # baseline
    events.clear()
    copy = _audit_scene("Kitchen.001", "sess-k", objects=0, keys=["mixar_tab_order", "mixie_ws_resume"])
    bpy.data.scenes.append(copy)
    added, removed = scene_identity.audit_scenes()
    assert (added, removed) == (["Kitchen.001"], [])
    assert len(events) == 1
    event, scene, fields = events[0]
    assert event == "scene.added" and scene is copy
    assert fields["objects"] == 0 and fields["world"] == "World"
    assert fields["keys"] == "mixar_tab_order,mixie_ws_resume"
    assert fields["operators"] == "scene.new" and fields["window_scene"] == "Kitchen"
    assert fields["tabs"] == 2


def test_a_removed_scene_is_logged_by_name(audit):
    bpy, events = audit
    a, b = _audit_scene("A"), _audit_scene("B")
    bpy.data.scenes.extend([a, b])
    scene_identity.audit_scenes()
    events.clear()
    bpy.data.scenes.remove(b)
    assert scene_identity.audit_scenes() == ([], ["B"])
    assert events[0][0] == "scene.removed" and events[0][2]["name"] == "B"


def test_the_audit_is_quiet_when_nothing_changed(audit):
    bpy, events = audit
    bpy.data.scenes.append(_audit_scene("A"))
    scene_identity.audit_scenes()
    events.clear()
    assert scene_identity.audit_scenes() == ([], [])
    assert events == []


def test_a_loaded_file_is_the_baseline_not_a_burst_of_added_lines(audit):
    bpy, events = audit
    bpy.data.scenes.extend([_audit_scene("A"), _audit_scene("B")])
    scene_identity._on_load_post()
    assert scene_identity._known_scene_names == {"A", "B"}
    assert [e[0] for e in events] == ["scenes.loaded"]
    assert events[0][2]["names"] == "A,B"
    events.clear()
    assert scene_identity.audit_scenes() == ([], [])


def test_the_grow_timer_audits_before_it_dedupes(audit, monkeypatch):
    bpy, events = audit
    order = []
    monkeypatch.setattr(scene_identity, "audit_scenes", lambda: order.append("audit") or ([], []))
    monkeypatch.setattr(scene_identity, "dedupe_session_ids", lambda: order.append("dedupe"))
    assert scene_identity._dedupe_later() is None
    assert order == ["audit", "dedupe"]


# ---------------------------------------------------------------------------
# Tab context on the chat payload
# ---------------------------------------------------------------------------


def test_the_chat_payload_names_the_tab_and_lists_the_table(live_bpy):
    kitchen = _audit_scene("Kitchen", "sess-k", objects=3)
    kitchen.mixie_chat_state = "BUSY"
    lane = _audit_scene("Workspace_abc", "agentlane:abc", objects=1)
    blank = _audit_scene("Scene 2", "", objects=2)
    live_bpy.data.scenes.extend([kitchen, lane, blank])
    live_bpy.context.window.scene = blank

    context = chat_payloads.collect_scene_context("sess-k")
    assert context["scene"] == "Kitchen"
    assert context["window_scene"] == "Scene 2"
    assert context["truncated"] is False
    tabs = {t["name"]: t for t in context["tabs"]}
    assert tabs["Kitchen"] == {"name": "Kitchen", "session": "sess-k", "objects": 3,
                               "state": "BUSY", "lane": False, "current": True}
    assert tabs["Workspace_abc"]["lane"] is True and tabs["Workspace_abc"]["current"] is False
    assert tabs["Scene 2"]["session"] == ""

    payload = chat_payloads.build_chat_payload(
        message="hi", instance_id="i", session_id="sess-k", plan_required=True,
        execution_required=True, approval_required=True, scene_context=context)
    assert payload["scene_context"] is context
    bare = chat_payloads.build_chat_payload(
        message="hi", instance_id="i", session_id="sess-k", plan_required=True,
        execution_required=True, approval_required=True)
    assert "scene_context" not in bare


def test_a_first_message_falls_back_to_the_window_scene(live_bpy):
    fresh = _audit_scene("Scene 3", "")
    live_bpy.data.scenes.append(fresh)
    live_bpy.context.window.scene = fresh
    context = chat_payloads.collect_scene_context("brand-new-sid")
    assert context["scene"] == "Scene 3"


# ---------------------------------------------------------------------------
# Support bundle
# ---------------------------------------------------------------------------


def test_the_bundle_ships_logs_ledgers_and_indexes_but_no_snapshots(tmp_path):
    logs = tmp_path / "logs"; logs.mkdir()
    (logs / "mixar-client.log").write_text("2026-09-28T05:18:05.000Z WARNING x: hello\n")
    (logs / "mixar-client.log.1").write_text("older\n")
    dossier = tmp_path / "scenes-dossier" / "sess-k"; dossier.mkdir(parents=True)
    (dossier / "events.jsonl").write_text('{"event":"tab.new"}\n')
    checkpoints = tmp_path / "checkpoints" / "sess-k"; checkpoints.mkdir(parents=True)
    (checkpoints / "index.json").write_text('{"checkpoints": []}')
    (checkpoints / "abc123.mixar").write_bytes(b"BLENDER" * 100)

    out = tmp_path / "bundle.zip"
    manifest = support_bundle.build_support_bundle(
        str(out), logs=str(logs), dossier=str(dossier.parent), checkpoints=str(checkpoints.parent),
        scenes=[{"name": "Kitchen.001", "objects": 0}], info={"mixar_version": "4.1.1"})
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        assert {"logs/mixar-client.log", "logs/mixar-client.log.1",
                "scenes-dossier/sess-k/events.jsonl", "checkpoints/sess-k/index.json",
                "scenes.json", "app.json", "manifest.json"} <= names
        assert not any(n.endswith(".mixar") for n in names)
        assert json.loads(zf.read("scenes.json"))[0]["name"] == "Kitchen.001"
        assert json.loads(zf.read("app.json"))["mixar_version"] == "4.1.1"
    assert manifest["scenes"] == 1 and manifest["skipped"] == []


def test_the_bundle_survives_missing_folders(tmp_path):
    out = tmp_path / "empty.zip"
    manifest = support_bundle.build_support_bundle(
        str(out), logs=str(tmp_path / "nope"), dossier="", checkpoints=str(tmp_path / "nada"),
        scenes=[], info={})
    assert manifest["files"] == ["scenes.json", "app.json"]
    assert os.path.getsize(out) > 0
