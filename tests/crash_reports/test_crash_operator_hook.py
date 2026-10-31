# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""A Mixar operator's exception reaches the crash reporter (Blender prints
operator errors with PyErr_Display, which never calls sys.excepthook)."""

import importlib

import pytest

import mixar.modules.common.crash_reports as crash_reports

# The analytics package re-exports a function named ``capture``; take the module.
capture = importlib.import_module("mixar.modules.common.analytics.capture")


def _operator(error):
    class FakeOperator:
        bl_idname = "mixar.fake_crashing_operator"

        def execute(self, context):
            raise error

    capture.instrument_operator_classes([FakeOperator])
    return FakeOperator


def test_operator_exception_is_reported_and_still_raised(monkeypatch):
    seen = []
    monkeypatch.setattr(crash_reports, "report_exception",
                        lambda exc_type, exc, tb, source: seen.append((exc_type, source)))
    operator = _operator(ZeroDivisionError("x"))
    with pytest.raises(ZeroDivisionError):
        operator().execute(None)
    assert seen == [(ZeroDivisionError, "operator")]


def test_a_broken_reporter_does_not_change_the_operator_error(monkeypatch):
    def broken(*_args, **_kwargs):
        raise RuntimeError("reporter down")

    monkeypatch.setattr(crash_reports, "report_exception", broken)
    operator = _operator(ValueError("y"))
    with pytest.raises(ValueError):
        operator().execute(None)
