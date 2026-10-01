# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Actions survive response loss, process restart, and conflicting UUID reuse."""

from uuid import uuid4

import pytest

from mixar.modules.common.ui_control.constants import UIError
from mixar.modules.common.ui_control.core.receipts import Receipts
from mixar.modules.common.ui_control.core.schema import validate


def test_restart_keeps_success_and_fences_unfinished_input(tmp_path):
    path = tmp_path / "receipts.sqlite"
    receipt = Receipts(path)
    completed, pending = str(uuid4()), str(uuid4())
    args = {"text": "sensitive typed contents"}
    digest = receipt.digest("scene", "act", args)
    receipt.claim(completed, digest)
    receipt.finish(completed, "succeeded")
    receipt.claim(pending, digest)
    receipt.close()
    reopened = Receipts(path)
    assert reopened.prior(completed, digest)["status"] == "succeeded"
    assert reopened.prior(pending, digest)["status"] == "outcome_unknown"
    with pytest.raises(UIError, match="different UI action"):
        reopened.prior(completed, reopened.digest("other-scene", "act", args))
    reopened.close()
    assert b"sensitive typed contents" not in path.read_bytes()


def test_two_identical_claims_cannot_dispatch_twice(tmp_path):
    receipt = Receipts(tmp_path / "receipts.sqlite")
    call_id = str(uuid4())
    digest = receipt.digest("scene", "act", {})
    receipt.claim(call_id, digest)
    with pytest.raises(UIError, match="already accepted"):
        receipt.claim(call_id, digest)
    assert receipt.status(call_id)["status"] == "accepted"
    receipt.close()


@pytest.mark.parametrize("args", [
    {"action": "eval", "context": "x", "target": "y", "code": "pass"},
    {"action": "gesture", "context": "x", "target": "y", "points": [[0, 0], [2, 0]]},
    {"action": "gesture", "context": "x", "target": "y", "points": [[0, 0], [1, 1]], "pressure": 1},
    {"action": "click", "context": "x", "target": "y", "operator": "wm.save_mainfile"},
])
def test_ui_arguments_cannot_smuggle_execution_or_unbounded_gestures(args):
    with pytest.raises(UIError):
        validate("mixar_ui_act", args)


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_wait_cannot_disable_the_request_deadline(timeout):
    with pytest.raises(UIError):
        validate("mixar_ui_wait", {"query": {}, "timeout": timeout})


def test_text_rejects_embedded_control_bytes_before_any_input():
    with pytest.raises(UIError):
        validate("mixar_ui_act", {"context": "c", "target": "t", "action": "set_text", "text": "abc\x00def"})
