# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""One selected package, inert inspection and fail-closed file boundaries."""
import base64
import io
import zipfile

import pytest
from mixar.modules.addon_project.core.publication_package import package


def fixture(tmp_path):
    addon = tmp_path / 'my_tool'; addon.mkdir()
    (addon / '__init__.py').write_text("bl_info={'name':'My tool','version':(1,2,3)}\nraise RuntimeError('never execute')")
    (addon / 'README.md').write_text('How to use this tool')
    other = tmp_path / 'another_tool'; other.mkdir()
    (other / '__init__.py').write_text('private = True')
    return addon


def test_only_selected_addon_is_packaged_and_no_code_runs(tmp_path):
    addon=fixture(tmp_path)
    (addon / '.env').write_text('SECRET=private')
    cache=addon / '__pycache__';cache.mkdir();(cache/'test.pyc').write_bytes(b'cache')
    result=package(tmp_path,'my_tool',workspace=True)
    assert result['info']['name']=='My tool'
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(result['archive']))) as z:
        assert set(z.namelist())=={'my_tool/__init__.py','my_tool/README.md'}
    assert str(tmp_path) not in result['archive']


def test_linked_or_unsupported_assets_refused(tmp_path):
    addon=fixture(tmp_path)
    (addon/'secret.py').symlink_to(tmp_path/'another_tool/__init__.py')
    with pytest.raises(ValueError,match='linked'):package(tmp_path,'my_tool',workspace=True)
    (addon/'secret.py').unlink()
    (addon/'scene.blend').write_bytes(b'project')
    with pytest.raises(ValueError,match='Unsupported'):package(tmp_path,'my_tool',workspace=True)


def test_umbrella_workspace_never_published(tmp_path):
    fixture(tmp_path);(tmp_path/'__init__.py').write_text('')
    with pytest.raises(ValueError):package(tmp_path,tmp_path.name,workspace=True)


def test_standalone_package_and_invalid_syntax(tmp_path):
    addon=fixture(tmp_path)
    assert len(package(addon,'my_tool')['files'])==2
    (addon/'__init__.py').write_text('def broken(')
    with pytest.raises(SyntaxError):package(addon,'my_tool')


def test_windows_junction_cannot_include_another_folder(tmp_path, monkeypatch):
    from mixar.modules.addon_project.core import publication_package as packager

    addon = fixture(tmp_path)
    junction = addon / 'external'
    junction.mkdir()
    (junction / 'private.py').write_text('secret = True')
    # Windows junctions look like ordinary directories to Path.is_symlink().
    # Exercise the common platform-aware classification on non-Windows CI.
    real_is_link = packager.is_link
    monkeypatch.setattr(packager, 'is_link', lambda path: path == junction or real_is_link(path))
    with pytest.raises(ValueError, match='linked folders'):
        package(tmp_path, 'my_tool', workspace=True)
