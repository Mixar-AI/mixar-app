# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bounds and pruning tests for Add-on Project indexing."""

import pytest

from mixar.modules.addon_project import paths as paths_module
from mixar.modules.addon_project.errors import AddonProjectError
from mixar.modules.addon_project.indexer import build_index


def test_index_prunes_ignored_trees_before_enforcing_file_limit(
    tmp_path, monkeypatch
):
    (tmp_path / "one.py").write_text("ONE = 1\n", encoding="utf-8")
    (tmp_path / "two.py").write_text("TWO = 2\n", encoding="utf-8")
    ignored = tmp_path / ".git" / "objects"
    ignored.mkdir(parents=True)
    (ignored / "not_project.py").write_text("SECRET = True\n", encoding="utf-8")
    monkeypatch.setattr(paths_module, "MAX_PROJECT_FILES", 2)

    files, _revision = build_index(tmp_path)
    assert [item["path"] for item in files] == ["one.py", "two.py"]

    (tmp_path / "three.py").write_text("THREE = 3\n", encoding="utf-8")
    with pytest.raises(AddonProjectError) as raised:
        build_index(tmp_path)
    assert raised.value.code == "project_too_large"
