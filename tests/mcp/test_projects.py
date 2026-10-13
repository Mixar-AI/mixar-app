# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""MCP clients reopen recent projects by name, never by path, and never lose work.

A project is listed and opened by a digest of its recent-files entry; opening
refuses while the open document is still working, and its unsaved changes are
saved or discarded only when the caller says so (after asking the user).
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from mixar.modules.common.ui_control.constants import UIError
from mixar.modules.common.ui_control.core import schema, service
from mixar.modules.common.ui_control.core.receipts import Receipts
from mixar.modules.mcp_bridge.core import connector, lease, projects, scene_tabs


@pytest.fixture
def mixar(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    files = {}
    for name in ("Garden Wedding", "Castle Lake"):
        files[name] = tmp_path / "work" / (name + ".mixar")
        files[name].parent.mkdir(exist_ok=True)
        files[name].write_bytes(b"BLENDER")
    notes = tmp_path / "work" / "notes.txt"
    notes.write_text("x")
    history = [files["Garden Wedding"], files["Castle Lake"], notes, tmp_path / "gone.mixar", files["Castle Lake"]]
    (config / "recent-files.txt").write_text("\n".join(str(p) for p in history) + "\n")
    state = SimpleNamespace(files=files, opened=[], saved=0, busy="",
                            data=SimpleNamespace(filepath=str(files["Garden Wedding"]), is_dirty=False))

    def open_mainfile(filepath):
        state.opened.append(filepath)
        state.data.filepath, state.data.is_dirty = filepath, False
        return {"FINISHED"}

    def save_mainfile():
        state.saved += 1
        state.data.is_dirty = False
        return {"FINISHED"}

    fake = SimpleNamespace(data=state.data, utils=SimpleNamespace(user_resource=lambda kind: str(config)),
                           ops=SimpleNamespace(wm=SimpleNamespace(open_mainfile=open_mainfile,
                                                                  save_mainfile=save_mainfile)))
    monkeypatch.setattr(projects, "bpy", fake)
    monkeypatch.setattr(projects, "_still_working", lambda: state.busy)
    monkeypatch.setattr(scene_tabs, "_gate", lambda: None)
    shown = SimpleNamespace(name="Lakeside", mixie_session_id="sess-lake")
    monkeypatch.setattr(scene_tabs, "_shown", lambda: shown)
    monkeypatch.setattr(scene_tabs, "_entry", lambda scene, s: {"name": scene.name, "session": scene.mixie_session_id})
    monkeypatch.setattr(scene_tabs, "list_scenes", lambda: {"scenes": [{"name": "Lakeside", "session": "sess-lake"}]})
    from mixar.modules.space_mixie_chat.core import scene_identity
    monkeypatch.setattr(scene_identity, "adopt_scene", lambda scene: False)
    return state


def project_id(mixar, name):
    return next(p["project"] for p in projects.list_projects()["projects"] if p["name"] == name)


def test_recent_projects_are_listed_by_name_never_by_path(mixar):
    listed = projects.list_projects()
    assert [p["name"] for p in listed["projects"]] == ["Garden Wedding", "Castle Lake"]
    assert [p["current"] for p in listed["projects"]] == [True, False]
    assert all(set(p) == {"project", "name", "folder", "modified", "current"} for p in listed["projects"])
    assert str(mixar.files["Castle Lake"].parent) not in repr(listed)


def test_opening_follows_the_shown_scene_of_the_loaded_file(mixar):
    result = projects.open_project(projects.preflight({"project": project_id(mixar, "Castle Lake")}))
    assert mixar.opened == [str(mixar.files["Castle Lake"])]
    assert result["opened"] is True and result["session"] == "sess-lake" and result["name"] == "Castle Lake"


def test_unsaved_changes_need_the_users_choice(mixar):
    mixar.data.is_dirty = True
    castle = project_id(mixar, "Castle Lake")
    with pytest.raises(UIError, match="Ask the user"):
        projects.preflight({"project": castle})
    projects.open_project(projects.preflight({"project": castle, "unsaved": "save"}), "save")
    assert mixar.saved == 1 and mixar.opened


def test_an_untitled_file_is_never_saved_silently(mixar):
    mixar.data.filepath, mixar.data.is_dirty = "", True
    castle = project_id(mixar, "Castle Lake")
    with pytest.raises(UIError, match="never been saved"):
        projects.preflight({"project": castle, "unsaved": "save"})
    projects.open_project(projects.preflight({"project": castle, "unsaved": "discard"}), "discard")
    assert mixar.saved == 0 and mixar.opened == [str(mixar.files["Castle Lake"])]


def test_work_in_progress_and_unknown_ids_refuse_before_anything_loads(mixar):
    mixar.busy = "generation jobs are still running and would import into a scene that closes"
    with pytest.raises(UIError, match="generation jobs"):
        projects.preflight({"project": project_id(mixar, "Castle Lake")})
    with pytest.raises(UIError, match="mixar_projects"):
        projects.preflight({"project": "0" * 16})
    assert mixar.opened == []


def test_the_open_project_is_not_reloaded(mixar):
    result = projects.open_project(projects.preflight({"project": project_id(mixar, "Garden Wedding")}))
    assert result["opened"] is False and mixar.opened == []


def test_a_retried_open_never_loads_twice(mixar, tmp_path, monkeypatch):
    receipts = Receipts(tmp_path / "receipts.sqlite")
    monkeypatch.setattr(service, "_receipts", receipts)
    monkeypatch.setattr(service, "_signed_in", lambda: None)
    monkeypatch.setattr(service.observe, "invalidate", lambda: None)
    call = str(uuid4())
    args = {"project": project_id(mixar, "Castle Lake")}
    request = SimpleNamespace(name="mixar_project_open", args=args, call_id=call, session="", claimed=False)
    first = service._scene_tool(request)
    receipts.finish(call, "succeeded")
    again = service._scene_tool(SimpleNamespace(**{**vars(request), "claimed": False}))
    assert first["opened"] is True and len(mixar.opened) == 1
    assert again["replayed"] is True
    receipts.close()


def test_schema_and_connector_treat_open_as_a_rebinding_local_tool():
    tools = {tool["name"]: tool for tool in schema.tools()}
    assert tools["mixar_projects"]["annotations"]["readOnlyHint"] is True
    assert tools["mixar_project_open"]["annotations"]["destructiveHint"] is True
    schema.validate("mixar_project_open", {"project": "a" * 16, "unsaved": "discard"})
    for bad in ({"project": "/Users/me/file.mixar"}, {"project": "a" * 16, "unsaved": "maybe"}):
        with pytest.raises(UIError):
            schema.validate("mixar_project_open", bad)
    assert "mixar_project_open".startswith(connector.LOCAL_PREFIXES)
    assert "mixar_project_open" in connector.REBINDS


def test_any_live_lease_counts_as_work_in_progress(monkeypatch):
    monkeypatch.setattr(lease, "_operations", {"s": SimpleNamespace(deadline=float("inf"))})
    assert lease.any_active_operation() is True
    monkeypatch.setattr(lease, "_operations", {})
    assert lease.any_active_operation() is False
