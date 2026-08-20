# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Crash and journal durability tests for Add-on Project Mode."""

import pytest

from mixar.modules.addon_project import transactions as transaction_module
from mixar.modules.addon_project.service import AddonProjectService


@pytest.fixture
def linked_project(tmp_path):
    project = tmp_path / "sample_addon"
    project.mkdir()
    (project / "__init__.py").write_text(
        "bl_info = {'name': 'Sample'}\n"
        "def register():\n    pass\n"
        "def unregister():\n    pass\n",
        encoding="utf-8",
    )
    (project / "operators.py").write_text(
        "def answer():\n    return 41\n",
        encoding="utf-8",
    )
    service = AddonProjectService(tmp_path / "client_state")
    return service, project, service.link(str(project))


def _stage_operator_change(service, description, *, include_panel=False):
    record = next(
        item for item in description["files"] if item["path"] == "operators.py"
    )
    changes = [{
        "path": "operators.py",
        "expected_sha256": record["sha256"],
        "content": "def answer():\n    return 42\n",
    }]
    if include_panel:
        changes.append({
            "path": "panels.py",
            "expected_sha256": None,
            "content": "class Panel:\n    pass\n",
        })
    return service.stage_patch(description["project_id"], {
        "expected_revision": description["revision"],
        "changes": changes,
    })


def test_failed_commit_journal_restores_project(linked_project, monkeypatch):
    service, project, description = linked_project
    staged = _stage_operator_change(service, description)
    real_write_json = transaction_module.write_json_atomic

    def fail_committed_journal(path, payload):
        if isinstance(payload, dict) and payload.get("status") == "committed":
            raise OSError("simulated journal failure")
        return real_write_json(path, payload)

    monkeypatch.setattr(
        transaction_module,
        "write_json_atomic",
        fail_committed_journal,
    )
    with pytest.raises(OSError, match="journal failure"):
        service.commit_patch(description["project_id"], staged["proposal_id"])
    assert (project / "operators.py").read_text(encoding="utf-8").endswith(
        "return 41\n"
    )
    assert service.history(description["project_id"])["transactions"] == []


def test_next_operation_recovers_interrupted_commit(linked_project, monkeypatch):
    service, project, description = linked_project
    staged = _stage_operator_change(service, description, include_panel=True)
    real_write = service.transactions._atomic_write

    def exit_on_second_file(path, content):
        if path.name == "panels.py":
            raise SystemExit("simulated process exit")
        return real_write(path, content)

    monkeypatch.setattr(service.transactions, "_atomic_write", exit_on_second_file)
    with pytest.raises(SystemExit, match="process exit"):
        service.commit_patch(description["project_id"], staged["proposal_id"])
    assert (project / "operators.py").read_text(encoding="utf-8").endswith(
        "return 42\n"
    )

    recovered = AddonProjectService(service.storage_dir)
    recovered.describe(description["project_id"])
    assert (project / "operators.py").read_text(encoding="utf-8").endswith(
        "return 41\n"
    )
    assert not (project / "panels.py").exists()


def test_next_operation_finishes_interrupted_rollback(
    linked_project, monkeypatch
):
    service, project, description = linked_project
    staged = _stage_operator_change(service, description, include_panel=True)
    committed = service.commit_patch(
        description["project_id"], staged["proposal_id"]
    )
    real_write = service.transactions._atomic_write

    def exit_before_second_restore(path, content):
        if path.name == "operators.py" and "return 41" in content:
            raise SystemExit("simulated rollback exit")
        return real_write(path, content)

    monkeypatch.setattr(
        service.transactions,
        "_atomic_write",
        exit_before_second_restore,
    )
    with pytest.raises(SystemExit, match="rollback exit"):
        service.rollback(
            description["project_id"],
            committed["transaction_id"],
            committed["revision"],
        )
    assert not (project / "panels.py").exists()
    assert (project / "operators.py").read_text(encoding="utf-8").endswith(
        "return 42\n"
    )

    recovered = AddonProjectService(service.storage_dir)
    recovered.describe(description["project_id"])
    assert (project / "operators.py").read_text(encoding="utf-8").endswith(
        "return 41\n"
    )
    assert not (project / "panels.py").exists()
    assert recovered.history(description["project_id"])["transactions"] == []
