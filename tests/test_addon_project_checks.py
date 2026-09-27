# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""What the reload check shows the agent: project frames, the console, every
submodule, and what unregister() left behind."""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault("keyring", MagicMock(name="keyring"))

from mixar.modules.addon_project.checks import project_frames, run_blender_reload
from mixar.modules.addon_project.service import AddonProjectService


class _AddonUtils:
    calls = []

    @staticmethod
    def disable(*_args, **_kwargs):
        pass

    @staticmethod
    def modules_refresh(*_args, **_kwargs):
        pass

    @staticmethod
    def enable(name, default_set=False, persistent=False, handle_error=None, **_kwargs):
        _AddonUtils.calls.append(name)
        return sys.modules[name]


@pytest.fixture
def package(tmp_path, monkeypatch):
    """A fresh package name per test so sys.modules never carries state over."""
    import bpy

    addons_dir = tmp_path / "user_addons"
    addons_dir.mkdir()
    monkeypatch.setattr(bpy.utils, "user_resource", lambda *_a, **_k: str(addons_dir))
    monkeypatch.setitem(sys.modules, "addon_utils", _AddonUtils)
    counter = {"n": 0}

    def _make(name, files):
        project = tmp_path / "root"
        pkg = project / name
        pkg.mkdir(parents=True, exist_ok=True)
        for relative, text in files.items():
            path = pkg / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return project

    return _make


INIT = "from . import ops\ndef register():\n    ops.register()\ndef unregister():\n    ops.unregister()\n"


def test_a_failure_names_the_project_frame_and_the_console(package):
    project = package("frames_sample", {
        "__init__.py": INIT,
        "ops.py": "print('loading ops')\ndef register():\n    raise ValueError('bad register')\ndef unregister():\n    pass\n",
    })
    result = run_blender_reload(project, "frames_sample")
    assert result["success"] is False
    assert result["message"] == "ValueError: bad register"
    assert [(f["path"], f["function"]) for f in result["frames"]] == [
        ("frames_sample/__init__.py", "register"), ("frames_sample/ops.py", "register")]
    assert result["frames"][-1]["line"] == 3 and result["frames"][-1]["code"] == "raise ValueError('bad register')"
    assert "loading ops" in result["console"]
    assert "traceback" not in result


def test_every_submodule_is_imported_even_when_init_never_wires_it(package):
    project = package("orphan_sample", {
        "__init__.py": "def register():\n    pass\ndef unregister():\n    pass\n",
        "forgotten.py": "import not_a_real_module_anywhere\n",
        "tests/__init__.py": "",
        "tests/test_x.py": "raise AssertionError('tests are not imported by the reload check')\n",
    })
    result = run_blender_reload(project, "orphan_sample")
    assert result["success"] is False
    assert result["message"].startswith("ModuleNotFoundError: No module named 'not_a_real_module_anywhere'")
    assert result["frames"][-1]["path"] == "orphan_sample/forgotten.py"


def test_unregister_leftovers_are_reported_as_leaks(package, monkeypatch):
    import bpy

    monkeypatch.setattr(bpy.app.handlers, "load_post", [], raising=False)
    project = package("leaky_sample", {
        "__init__.py": (
            "import bpy\n"
            "class LEAKY_OT_thing:\n    pass\n"
            "def on_load(_scene):\n    pass\n"
            "def register():\n"
            "    bpy.types.LEAKY_OT_thing = LEAKY_OT_thing\n"
            "    bpy.app.handlers.load_post.append(on_load)\n"
            "def unregister():\n    pass\n"
        ),
    })
    result = run_blender_reload(project, "leaky_sample")
    assert result["success"] is False
    assert result["leaks"] == [
        {"kind": "class", "name": "LEAKY_OT_thing"},
        {"kind": "handler", "name": "load_post: on_load"},
    ]
    assert result["message"].startswith("RegistrationLeak: unregister() left 2 registration(s) behind")


def test_an_enabled_addon_that_fails_to_re_enable_reports_the_reason(package, monkeypatch):
    project = package("reenable_sample", {"__init__.py": "def register():\n    pass\ndef unregister():\n    pass\n"})
    import importlib
    sys.path.insert(0, str(project))
    try:
        old = importlib.import_module("reenable_sample")
        old.__addon_enabled__ = True

        def failing_enable(name, handle_error=None, **_kwargs):
            try:
                raise RuntimeError("keymap conflict")
            except RuntimeError as exc:
                handle_error(exc)
            return None

        monkeypatch.setattr(_AddonUtils, "enable", staticmethod(failing_enable))
        result = run_blender_reload(project, "reenable_sample")
    finally:
        sys.path.remove(str(project))
    assert result["success"] is False and result["message"] == "RuntimeError: keymap conflict"


def test_project_frames_drop_everything_outside_the_root(tmp_path):
    try:
        raise KeyError("x")
    except KeyError as exc:
        assert project_frames(exc, tmp_path) == []


def test_scrub_keeps_frames_and_only_hides_the_root(tmp_path):
    value = {"frames": [{"path": "pkg/a.py", "line": 3}], "message": f"boom at {tmp_path}/pkg/a.py"}
    scrubbed = AddonProjectService._scrub(value, tmp_path)
    assert scrubbed["frames"] == value["frames"]
    assert scrubbed["message"] == "boom at <project>/pkg/a.py"


# ── run_tests ────────────────────────────────────────────────────────────

from mixar.modules.addon_project.addon_tests import run_addon_tests  # noqa: E402

OPS = "def answer():\n    return 42\n"


def test_the_addon_s_own_unittest_package_runs_with_relative_imports(package):
    project = package("tested_sample", {
        "__init__.py": "def register():\n    pass\ndef unregister():\n    pass\n",
        "ops.py": OPS,
        "tests/__init__.py": "",
        "tests/test_ops.py": (
            "import unittest\nfrom .. import ops\n"
            "class T(unittest.TestCase):\n"
            "    def test_answer(self):\n        print('checking')\n        self.assertEqual(ops.answer(), 42)\n"
            "    def test_wrong(self):\n        self.assertEqual(ops.answer(), 41, 'off by one')\n"
            "    @unittest.skip('later')\n    def test_later(self):\n        pass\n"
        ),
    })
    result = run_addon_tests(project, "tested_sample")
    assert result["success"] is False and result["ran"] == 3   # unittest counts the skip
    assert (result["passed"], result["failed"], result["error"], result["skipped"]) == (1, 1, 0, 1)
    by_id = {t["id"]: t for t in result["tests"]}
    assert by_id["tests.test_ops.T.test_answer"] == {"id": "tests.test_ops.T.test_answer", "status": "passed"}
    wrong = by_id["tests.test_ops.T.test_wrong"]
    assert wrong["status"] == "failed" and wrong["message"].startswith("AssertionError: 42 != 41 : off by one")
    assert wrong["frames"][-1]["path"] == "tested_sample/tests/test_ops.py" and wrong["frames"][-1]["function"] == "test_wrong"
    assert by_id["tests.test_ops.T.test_later"] == {"id": "tests.test_ops.T.test_later", "status": "skipped", "message": "later"}
    assert "checking" in result["console"]
    assert result["message"] == "1 passed, 1 failed, 1 skipped"

    # An edited test runs as edited: the module is re-imported every run.
    (project / "tested_sample" / "tests" / "test_ops.py").write_text(
        "import unittest\nfrom .. import ops\n"
        "class T(unittest.TestCase):\n    def test_answer(self):\n        self.assertEqual(ops.answer(), 42)\n",
        encoding="utf-8")
    again = run_addon_tests(project, "tested_sample")
    assert again["success"] is True and again["ran"] == 1 and again["message"] == "1 passed"


def test_no_tests_package_is_a_plain_message_not_a_pass(package):
    project = package("untested_sample", {"__init__.py": "def register():\n    pass\ndef unregister():\n    pass\n"})
    result = run_addon_tests(project, "untested_sample")
    assert result["success"] is False and result["tests"] == []
    assert result["message"].startswith("No untested_sample/tests package")
    empty = package("emptytests_sample", {"__init__.py": "", "tests/__init__.py": ""})
    result = run_addon_tests(empty, "emptytests_sample")
    assert result["success"] is False and result["ran"] == 0 and "No tests found" in result["message"]


def test_a_test_module_that_fails_to_import_is_an_error_with_its_frame(package):
    project = package("broken_tests_sample", {
        "__init__.py": "",
        "tests/__init__.py": "",
        "tests/test_broken.py": "import unittest\nraise RuntimeError('no such fixture')\n",
    })
    result = run_addon_tests(project, "broken_tests_sample")
    assert result["success"] is False and result["error"] == 1
    (record,) = [t for t in result["tests"] if t["status"] == "error"]
    assert "no such fixture" in record["message"]


def test_dispatch_runs_tests_and_sets_the_entrypoint(tmp_path, monkeypatch, set_addon_projects_root):
    from mixar.modules.addon_project.constants import PROTOCOL_VERSION, RPC_RUN_TESTS, RPC_SET_ENTRYPOINT
    from mixar.modules.addon_project.service import AddonProjectService

    root = set_addon_projects_root(tmp_path / "Mixar Addons")
    for name in ("alpha_tool", "beta_tool"):
        pkg = root / name
        (pkg / "tests").mkdir(parents=True)
        (pkg / "__init__.py").write_text("bl_info = {'name': 'x'}\ndef register():\n    pass\ndef unregister():\n    pass\n")
        (pkg / "tests" / "__init__.py").write_text("")
        (pkg / "tests" / "test_it.py").write_text(
            f"import unittest\nclass T(unittest.TestCase):\n    def test_name(self):\n        self.assertEqual('{name}', __package__.split('.')[0])\n")
    service = AddonProjectService(tmp_path / "state")
    description = service.link_workspace_root()
    project_id = description["project_id"]
    lease = service.issue_lease(project_id)["lease_id"]
    wire = {"protocol_version": PROTOCOL_VERSION, "project_id": project_id, "lease_id": lease}

    picked = service.dispatch(RPC_SET_ENTRYPOINT, {**wire, "entrypoint": "beta_tool"})
    assert picked["success"] is True and picked["entrypoint"] == "beta_tool"
    result = service.dispatch(RPC_RUN_TESTS, wire)
    assert result["success"] is True and result["entrypoint"] == "beta_tool" and result["ran"] == 1
    other = service.dispatch(RPC_RUN_TESTS, {**wire, "entrypoint": "alpha_tool"})
    assert other["success"] is True and other["entrypoint"] == "alpha_tool"
    assert "revision" in result and str(root) not in repr(result)


def test_a_standalone_root_package_keeps_its_tests_at_root_tests(tmp_path, monkeypatch):
    """The project folder IS the package: <root>/tests, not <root>/<root>/tests."""
    import bpy
    monkeypatch.setitem(sys.modules, "addon_utils", _AddonUtils)
    project = tmp_path / "solo_addon_sample"
    (project / "tests").mkdir(parents=True)
    (project / "__init__.py").write_text("def register():\n    pass\ndef unregister():\n    pass\n")
    (project / "tests" / "__init__.py").write_text("")
    (project / "tests" / "test_solo.py").write_text(
        "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n")
    result = run_addon_tests(project, "solo_addon_sample")
    assert result["success"] is True and result["ran"] == 1


def test_subtest_failures_and_unexpected_successes_are_recorded(package):
    project = package("subtest_sample", {
        "__init__.py": "",
        "tests/__init__.py": "",
        "tests/test_sub.py": (
            "import unittest\n"
            "class T(unittest.TestCase):\n"
            "    def test_each(self):\n"
            "        for n in (1, 2, 3):\n"
            "            with self.subTest(n=n):\n"
            "                self.assertNotEqual(n, 2, 'two is out')\n"
            "    def test_boom(self):\n"
            "        with self.subTest(part='x'):\n"
            "            raise RuntimeError('exploded')\n"
            "    @unittest.expectedFailure\n"
            "    def test_surprise(self):\n        pass\n"
        ),
    })
    result = run_addon_tests(project, "subtest_sample")
    assert result["success"] is False
    by_status = {r["id"]: r for r in result["tests"]}
    assert by_status["tests.test_sub.T.test_each (n=2)"]["status"] == "failed"
    assert "two is out" in by_status["tests.test_sub.T.test_each (n=2)"]["message"]
    assert by_status["tests.test_sub.T.test_boom (part='x')"]["status"] == "error"
    assert by_status["tests.test_sub.T.test_surprise"]["status"] == "failed"
    assert (result["failed"], result["error"]) == (2, 1)
