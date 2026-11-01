# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Where faulthandler starts and stops: the app's crash reporter bootstrap and
the render worker's entry point."""

import importlib.util
import io
import os
from pathlib import Path

import pytest

from mixar.modules.common.crash_reports.core import pyfault

SCRIPTS = Path(__file__).resolve().parents[2] / "src" / "scripts" / "mixar"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def calls(monkeypatch):
    seen = []
    monkeypatch.setattr(pyfault, "enable", lambda directory, pid=None: seen.append(("enable", directory)))
    monkeypatch.setattr(pyfault, "disable", lambda remove=True: seen.append(("disable", remove)))
    return seen


def test_the_app_enables_faulthandler_in_its_state_dir_and_a_clean_quit_removes_it(tmp_path, calls):
    module = _load(SCRIPTS / "bootstrap" / "crash_reports_module.py", "crash_reports_module_under_test")
    module._enable_faulthandler(str(tmp_path))
    assert calls == [("enable", str(tmp_path))]
    breadcrumb = tmp_path / ("session-%d.json" % os.getpid())
    dump = tmp_path / ("pyfault-%d.txt" % os.getpid())
    breadcrumb.write_text("{}")
    dump.write_text("")
    module._state_path = str(tmp_path)
    module._on_exit()
    assert calls[-1] == ("disable", True)
    assert not breadcrumb.exists() and not dump.exists()


def test_the_worker_enables_faulthandler_first_and_disables_it_on_a_clean_exit(monkeypatch, tmp_path, calls):
    module = _load(SCRIPTS / "modules" / "common" / "render_worker" / "worker_main.py", "worker_main_under_test")
    for name in ("_lower_priority", "_register_ui_modules", "_drop_handlers", "_enable_compute_device"):
        monkeypatch.setattr(module, name, lambda name=name: calls.append((name,)))
    monkeypatch.setattr(module, "_emit", lambda message: calls.append(("emit", message["type"])))
    monkeypatch.setattr(module.sys, "stdin", io.StringIO(""))
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr("tempfile.tempdir", None)

    def _exit(code):
        raise SystemExit(code)

    monkeypatch.setattr(module.os, "_exit", _exit)
    with pytest.raises(SystemExit):
        module.main()
    assert calls[0] == ("enable", os.path.realpath(str(tmp_path))) or calls[0] == ("enable", str(tmp_path))
    assert calls[1] == ("_lower_priority",)
    assert ("disable", True) in calls
    assert calls.index(("emit", "exit")) < calls.index(("disable", True))
