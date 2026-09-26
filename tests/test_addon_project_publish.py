# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Publish-to-Community: packaging, the service surface and the community client."""

import ast
import io
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault("keyring", MagicMock(name="keyring"))

from mixar.modules.addon_project.errors import AddonProjectError
from mixar.modules.addon_project.packaging import build_addon_zip, read_bl_info
from mixar.modules.addon_project.service import AddonProjectService

ADDON = (
    "bl_info = {'name': 'Quick Bevel', 'version': (1, 2, 0), 'blender': (4, 2, 0),\n"
    "           'category': 'Mesh', 'description': 'One-click bevel'}\n"
    "def register():\n    pass\n"
    "def unregister():\n    pass\n"
)
REPO = Path(__file__).resolve().parents[1]


def _workspace(tmp_path, name="quick_bevel", source=ADDON):
    package = tmp_path / "Mixar Addons" / name
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(source, encoding="utf-8")
    return package.parent


def _names(data: bytes):
    return sorted(zipfile.ZipFile(io.BytesIO(data)).namelist())


def test_zip_holds_one_package_and_nothing_machine_specific(tmp_path):
    root = _workspace(tmp_path)
    package = root / "quick_bevel"
    (package / "ops.py").write_text("x = 1\n")
    (package / "icons").mkdir()
    (package / "icons" / "bevel.png").write_bytes(b"\x89PNG")
    (package / "__pycache__").mkdir()
    (package / "__pycache__" / "ops.cpython-311.pyc").write_bytes(b"\0")
    (root / ".mixar").mkdir()
    (root / ".mixar" / "addon-project.json").write_text("{}")
    (root / "other_addon").mkdir()
    (root / "other_addon" / "__init__.py").write_text(ADDON)

    packaged = build_addon_zip(root, "quick_bevel")

    assert packaged.filename == "quick_bevel.zip"
    assert _names(packaged.data) == [
        "quick_bevel/__init__.py",
        "quick_bevel/icons/bevel.png",
        "quick_bevel/ops.py",
    ]
    assert packaged.title == "Quick Bevel" and packaged.description == "One-click bevel"
    assert str(tmp_path).encode() not in packaged.data
    # Deterministic: the same source zips to the same bytes.
    assert build_addon_zip(root, "quick_bevel").data == packaged.data


def test_symlinks_are_not_followed(tmp_path):
    root = _workspace(tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_text("token")
    (root / "quick_bevel" / "leak.txt").symlink_to(secret)
    assert "quick_bevel/leak.txt" not in _names(build_addon_zip(root, "quick_bevel").data)


@pytest.mark.parametrize(
    ("setup", "code"),
    [
        (lambda p: (p / "native.so").write_bytes(b"\x7fELF"), "unsupported_file"),
        (lambda p: (p / "__init__.py").write_text("def register(): pass\n"), "bl_info_missing"),
    ],
)
def test_refuses_what_the_community_would_reject(tmp_path, setup, code):
    root = _workspace(tmp_path)
    setup(root / "quick_bevel")
    with pytest.raises(AddonProjectError) as exc:
        build_addon_zip(root, "quick_bevel")
    assert exc.value.code == code


def test_read_bl_info_never_executes():
    assert read_bl_info("import os\nos.system('boom')\nbl_info = {'name': 'Safe'}") == {"name": "Safe"}
    assert read_bl_info("bl_info = dict(name='x')") == {}


def test_service_refuses_to_package_code_that_does_not_compile(tmp_path):
    root = _workspace(tmp_path, source=ADDON + "def broken(:\n")
    service = AddonProjectService(tmp_path / "state")
    project_id = service.link(str(root))["project_id"]
    with pytest.raises(AddonProjectError) as exc:
        service.package_for_publish(project_id, "quick_bevel")
    assert exc.value.code == "checks_failed"
    assert "quick_bevel/__init__.py" in exc.value.message


def test_service_packages_and_remembers_the_post(tmp_path):
    root = _workspace(tmp_path)
    service = AddonProjectService(tmp_path / "state")
    project_id = service.link(str(root))["project_id"]
    packaged = service.package_for_publish(project_id, "quick_bevel")
    assert packaged.package == "quick_bevel"
    assert service.community_post_id(project_id, "quick_bevel") is None
    service.remember_community_post(project_id, "quick_bevel", "post-1")
    assert service.community_post_id(project_id, "quick_bevel") == "post-1"
    # Machine-local state only: nothing is written into the project folder.
    assert not list(root.rglob("community_posts.json"))


# -- community client --------------------------------------------------------


class FakeHTTP:
    """Records calls and answers like the community API envelope."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def request(self, method, endpoint, raise_for_status=True, **kwargs):
        self.calls.append((method, endpoint, kwargs.get("json")))
        status, data = self.routes[(method, endpoint)]
        body = {"status": "success" if status < 400 else "failure", "message": "m", "data": data}
        return SimpleNamespace(success=status < 400, status_code=status, data=body)


def _service(routes, monkeypatch, puts):
    from mixar.modules.common.api.services import community_service

    monkeypatch.setattr(community_service, "get_access_token", lambda: "tok")

    def fake_put(method, url, data=None, headers=None, timeout=None):
        puts.append((url, headers))
        return SimpleNamespace(ok=True, status_code=200)

    monkeypatch.setattr(community_service.requests, "request", fake_put)
    http = FakeHTTP(routes)
    return community_service.CommunityService("https://c-api.test/api/v1", "https://c.test", http=http), http


UPLOAD_ROUTES = {
    ("GET", "profiles/me"): (200, {"profile": {"handle": "alice"}}),
    ("POST", "uploads"): (201, {"file": {"id": "f-new"}, "upload": {"url": "https://s3.test/put", "method": "PUT", "headers": {"Content-Type": "application/octet-stream"}}}),
    ("POST", "uploads/f-new/complete"): (200, {"id": "f-new"}),
}


def test_first_publish_creates_an_addon_draft_without_leaking_the_token_to_storage(monkeypatch):
    puts = []
    routes = {**UPLOAD_ROUTES, ("POST", "posts"): (201, {"id": "p1"})}
    service, http = _service(routes, monkeypatch, puts)
    result = service.publish_addon("quick_bevel.zip", b"zip", title="Quick Bevel", description="d")
    assert (result.post_id, result.web_url, result.created) == ("p1", "https://c.test/p/p1", True)
    declared = next(j for m, e, j in http.calls if e == "uploads")
    assert declared["kind"] == "addon" and declared["role"] == "download" and len(declared["sha256"]) == 64
    created = next(j for m, e, j in http.calls if e == "posts")
    assert created["kind"] == "addon"
    assert ("POST", "posts/p1/publish", None) not in http.calls  # stays a draft
    assert "Authorization" not in puts[0][1]


def test_republish_swaps_only_the_addon_zip(monkeypatch):
    puts = []
    post = {
        "viewer": {"is_owner": True},
        "previews": [{"id": "img"}],
        "downloads": [{"id": "f-old", "kind": "addon"}, {"id": "readme", "kind": "archive"}],
    }
    routes = {**UPLOAD_ROUTES, ("GET", "posts/p1"): (200, post), ("PATCH", "posts/p1"): (200, {"id": "p1"})}
    service, http = _service(routes, monkeypatch, puts)
    result = service.publish_addon("q.zip", b"zip", title="Q", description="", existing_post_id="p1")
    assert result.created is False
    patch = next(j for m, e, j in http.calls if m == "PATCH")
    assert patch == {"file_ids": ["img", "readme", "f-new"]}


def test_missing_handle_is_a_clear_error(monkeypatch):
    from mixar.modules.common.api.services.community_service import CommunityError

    service, _ = _service({("GET", "profiles/me"): (200, {"profile": None})}, monkeypatch, [])
    with pytest.raises(CommunityError) as exc:
        service.publish_addon("q.zip", b"zip", title="Q", description="")
    assert exc.value.code == "profile_required" and "https://c.test/settings/profile" in str(exc.value)


def test_local_dev_upload_to_the_community_api_carries_the_token(monkeypatch):
    puts = []
    routes = dict(UPLOAD_ROUTES)
    routes[("POST", "uploads")] = (201, {"file": {"id": "f-new"}, "upload": {"url": "https://c-api.test/api/v1/uploads/f-new/content", "method": "PUT", "headers": {}}})
    routes[("POST", "posts")] = (201, {"id": "p1"})
    service, _ = _service(routes, monkeypatch, puts)
    service.publish_addon("q.zip", b"zip", title="Q", description="")
    assert puts[0][1]["Authorization"] == "Bearer tok"


def test_operator_has_no_dialog_and_keeps_bpy_off_the_worker():
    source = (REPO / "src/scripts/mixar/modules/addon_project/ui/publish_ops.py").read_text()
    tree = ast.parse(source)
    operator = next(n for n in tree.body if isinstance(n, ast.ClassDef))
    assert "invoke" not in {f.name for f in operator.body if isinstance(f, ast.FunctionDef)}
    work = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_work")
    assert "bpy" not in ast.unparse(work)
    assert "bpy.app.timers.register" in source


def test_publish_is_reachable_from_the_file_menu():
    # The Agent island's native composer doesn't draw the Python project
    # controls, so File > Add-on Projects is the surface that must carry it.
    ui = REPO / "src/scripts/mixar/modules/addon_project/ui"
    topbar = (ui / "topbar_menu.py").read_text()
    assert "TOPBAR_MT_file.append" in topbar and "MIXAR_MT_addon_project_workspace" in topbar
    assert '"mixar.addon_project_publish"' in (ui / "workspace_ops.py").read_text()
