# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A UI module whose first exec fails must be re-executed by the retry pass.

mixar-backend#2004: the deferred UI loader put each module in ``sys.modules``
before executing it and kept it there when the exec raised. The retry pass then
found that half-executed shell, reused it (no ``register()``, no ``classes``)
and registered nothing, so the BYOK WindowManager properties never existed and
``MIXAR_BYOK_OT_open_dialog.invoke`` raised ``AttributeError: 'WindowManager'
object has no attribute 'byok_dialog_state'``.

The retry covers load-order errors (``ImportError``, ``AttributeError``) and a
transient ``OSError`` reading the file or its bytecode. Anything else is a bug
in the module and must stay loud: it is logged at once as an ERROR with its
traceback, under the "Failed to load UI module" text QA greps for
(``tests/qa/zen_object_controls_e2e.py``, the QA harness's ``startup_health``),
and so is a module that fails its retry. Production logs ERROR and above only.
"""

import importlib.util
import logging
import sys
from pathlib import Path

import pytest

BOOTSTRAP = Path(__file__).resolve().parents[1] / "src/scripts/startup/bootstrap/__init__.py"
PACKAGE = "mixar.modules.qa_np2004"
DOTTED_NAME = "qa_np2004.ui.properties.flaky_props"  # as the loader logs it
MODULE_NAME = f"mixar.modules.{DOTTED_NAME}"
GATE = "qa_np2004_gate"

FLAKY_SOURCE = f'''
import sys
if sys.modules.get({GATE!r}) is None:
    raise ImportError("transient first-pass failure")
REGISTERED = []
def register():
    REGISTERED.append(True)
'''

REGISTER_RAISES_SOURCE = '''
class Panel:
    is_registered = False
classes = (Panel,)
def register():
    Panel.is_registered = True
    raise RuntimeError("register() failed after its classes registered")
'''


@pytest.fixture
def loader(tmp_path, monkeypatch, caplog):
    # The bootstrap inserts into sys.path when it is executed.
    monkeypatch.setattr(sys, "path", list(sys.path))
    spec = importlib.util.spec_from_file_location("qa_np2004_bootstrap", BOOTSTRAP)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ui_file = tmp_path / "qa_np2004" / "ui" / "properties" / "flaky_props.py"
    ui_file.parent.mkdir(parents=True)
    ui_file.write_text(FLAKY_SOURCE)
    monkeypatch.setattr(module, "_ui_modules_path", tmp_path)
    monkeypatch.delitem(sys.modules, MODULE_NAME, raising=False)
    monkeypatch.setitem(sys.modules, GATE, None)
    # Parent packages as the app makes them, so a plain import finds the file.
    module._discover_and_register_subpackages(tmp_path / "qa_np2004", PACKAGE)
    # A plain stdlib logger: other tests can leave a stubbed get_logger in sys.modules.
    monkeypatch.setattr(module, "logger", logging.getLogger("qa_np2004.bootstrap"))
    caplog.set_level(logging.WARNING, logger="qa_np2004.bootstrap")
    yield module, ui_file, tmp_path
    for name in [n for n in sys.modules if n.startswith(PACKAGE)]:
        del sys.modules[name]


def _errors(caplog):
    # By number: the app's console formatter rewrites record.levelname.
    return [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_failed_exec_is_not_left_in_sys_modules(loader):
    bootstrap, ui_file, modules_path = loader
    bootstrap._register_single_ui_module(ui_file, modules_path)
    assert [f for f, _ in bootstrap._ui_failed_modules] == [ui_file]
    assert MODULE_NAME not in sys.modules
    assert bootstrap._loaded_ui_modules == []


def test_retry_pass_re_executes_and_registers(loader, monkeypatch):
    bootstrap, ui_file, modules_path = loader
    bootstrap._register_single_ui_module(ui_file, modules_path)
    monkeypatch.setitem(sys.modules, GATE, object())  # the transient cause is gone
    bootstrap._retry_failed_ui_modules()
    module = sys.modules[MODULE_NAME]
    assert module.REGISTERED == [True]
    assert bootstrap._loaded_ui_modules == [module]
    assert bootstrap._ui_failed_modules == []


def test_import_before_the_retry_gets_the_module_the_retry_registers(loader, monkeypatch):
    bootstrap, ui_file, modules_path = loader
    bootstrap._register_single_ui_module(ui_file, modules_path)
    monkeypatch.setitem(sys.modules, GATE, object())  # the transient cause is gone
    # A sibling loaded later in the first pass imports from the module. With
    # the failed shell left in sys.modules this raised ImportError "cannot
    # import name 'REGISTERED'", and took the sibling down with it.
    sibling = {}
    exec(f"from {MODULE_NAME} import REGISTERED", sibling)
    module = sys.modules[MODULE_NAME]
    assert sibling["REGISTERED"] is module.REGISTERED
    assert module.REGISTERED == []  # imported, not registered yet
    bootstrap._retry_failed_ui_modules()
    assert sys.modules[MODULE_NAME] is module
    assert module.REGISTERED == [True]
    assert bootstrap._loaded_ui_modules == [module]
    assert bootstrap._ui_failed_modules == []


def test_transient_os_error_is_retried_too(loader, monkeypatch, caplog):
    bootstrap, ui_file, modules_path = loader
    ui_file.write_text(FLAKY_SOURCE.replace("ImportError", "OSError"))
    bootstrap._register_single_ui_module(ui_file, modules_path)
    assert [(f, type(e)) for f, e in bootstrap._ui_failed_modules] == [(ui_file, OSError)]
    assert MODULE_NAME not in sys.modules
    monkeypatch.setitem(sys.modules, GATE, object())  # the transient cause is gone
    bootstrap._retry_failed_ui_modules()
    module = sys.modules[MODULE_NAME]
    assert module.REGISTERED == [True]
    assert bootstrap._loaded_ui_modules == [module]
    assert bootstrap._ui_failed_modules == []
    # A deferral the retry cures happens on healthy builds: no ERROR and no
    # traceback, either of which fails QA's startup check.
    assert [r for r in caplog.records if r.levelno >= logging.ERROR or r.exc_info] == []


@pytest.mark.parametrize("error", [ValueError, EOFError])
def test_other_first_failure_is_an_error_at_once_and_not_retried(loader, monkeypatch, caplog, error):
    bootstrap, ui_file, modules_path = loader
    ui_file.write_text(FLAKY_SOURCE.replace("ImportError", error.__name__))
    bootstrap._register_single_ui_module(ui_file, modules_path)
    assert bootstrap._ui_failed_modules == []
    assert MODULE_NAME not in sys.modules
    (record,) = _errors(caplog)
    assert f"Failed to load UI module {DOTTED_NAME}: transient first-pass failure" in record.getMessage()
    assert record.exc_info[0] is error and record.exc_info[2] is not None
    monkeypatch.setitem(sys.modules, GATE, object())  # would load now, but is not retried
    bootstrap._retry_failed_ui_modules()
    assert MODULE_NAME not in sys.modules
    assert bootstrap._loaded_ui_modules == []
    assert len(_errors(caplog)) == 1


def test_register_failing_after_its_classes_registered_is_an_error(loader, caplog):
    # A register() that raises a non-load-order error after registering its
    # classes must be an ERROR now: deferring it to the retry would find every
    # class "already registered" and skip the module silently.
    bootstrap, ui_file, modules_path = loader
    ui_file.write_text(REGISTER_RAISES_SOURCE)
    bootstrap._register_single_ui_module(ui_file, modules_path)
    bootstrap._retry_failed_ui_modules()
    (record,) = _errors(caplog)
    assert f"Failed to load UI module {DOTTED_NAME}: register() failed" in record.getMessage()
    assert record.exc_info[0] is RuntimeError and record.exc_info[2] is not None
    assert bootstrap._loaded_ui_modules == []


def test_module_failing_its_retry_is_an_error_with_both_failures(loader, caplog):
    bootstrap, ui_file, modules_path = loader
    bootstrap._register_single_ui_module(ui_file, modules_path)
    ((_, first_error),) = bootstrap._ui_failed_modules
    assert _errors(caplog) == []  # deferred: a warning so far
    bootstrap._retry_failed_ui_modules()  # the cause is still there
    (record,) = _errors(caplog)
    message = record.getMessage()
    assert f"Failed to load UI module {DOTTED_NAME} after retry: transient first-pass failure" in message
    assert f"(first failure: {first_error!r})" in message
    retry_type, retry_error, retry_traceback = record.exc_info
    assert retry_type is ImportError and retry_error is not first_error
    assert retry_traceback is not None
    assert bootstrap._ui_failed_modules == []
    assert MODULE_NAME not in sys.modules
