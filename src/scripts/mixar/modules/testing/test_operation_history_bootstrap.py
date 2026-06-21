# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit test for the operation_history bootstrap module.

The bootstrap's register()/unregister() import operation_history.core.capture_service,
which does a module-top ``from bpy.app.handlers import persistent`` that the bare root
conftest bpy stub does not satisfy. We install the richer test bpy mock
(``mock_bpy.install_bpy_mock``, which registers ``bpy.app.handlers`` + ``bpy.app.timers``)
before importing the bootstrap module so register() actually exercises the wiring paths
instead of silently swallowing an ImportError.
"""

import os
import sys

_test_dir = os.path.dirname(os.path.abspath(__file__))
_scripts_dir = os.path.abspath(os.path.join(_test_dir, "..", "..", ".."))  # -> src/scripts
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()


def test_register_unregister_no_raise():
    from mixar.bootstrap import operation_log_module as M

    M.register()
    M.unregister()   # idempotent; bpy is stubbed so this exercises the wiring paths


def test_register_runs_capture_service_wiring():
    """Positive evidence: capture_service.register() runs without raising under the mock
    (the bootstrap's try/except would otherwise hide a real registration failure)."""
    from mixar.modules.operation_history.core import capture_service

    capture_service.register()
    capture_service.unregister()
