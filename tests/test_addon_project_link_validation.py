# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Link-time Blender module-name validation for Add-on Project Mode."""

import sys
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault("keyring", MagicMock(name="keyring"))

from mixar.modules.addon_project.errors import AddonProjectError  # noqa: E402
from mixar.modules.addon_project.service import AddonProjectService  # noqa: E402


def test_link_rejects_invalid_new_project_folder_before_writing_metadata(tmp_path):
    project = tmp_path / "mixar-add-on"
    project.mkdir()
    service = AddonProjectService(tmp_path / "client_state")

    with pytest.raises(AddonProjectError) as error:
        service.link(str(project))

    assert error.value.code == "invalid_project_folder_name"
    assert "mixar_add_on" in error.value.message
    assert str(tmp_path) not in error.value.message
    assert not (project / ".mixar").exists()


def test_link_allows_repository_name_when_it_contains_a_valid_addon_package(
    tmp_path,
):
    project = tmp_path / "studio-tools-repository"
    addon = project / "studio_tools"
    addon.mkdir(parents=True)
    (addon / "__init__.py").write_text(
        "bl_info = {'name': 'Studio Tools'}\n"
        "def register():\n    pass\n"
        "def unregister():\n    pass\n",
        encoding="utf-8",
    )
    service = AddonProjectService(tmp_path / "client_state")

    description = service.link(str(project))

    assert description["entrypoint"] == "studio_tools"
