# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""An expired controller must not let scene scripts enter its unfinished modal."""

from types import SimpleNamespace

import pytest

from mixar.modules.common.ui_control.constants import UIError
from mixar.modules.common.ui_control.core import ownership


@pytest.fixture
def native(monkeypatch):
    state = SimpleNamespace(generation=1, modals=1)
    win = SimpleNamespace(as_pointer=lambda: 10, mixar_ui_modal_count=lambda: state.modals)

    def end(**kwargs):
        state.generation += 1

    wm = SimpleNamespace(windows=[win], mixar_ui_generation=lambda: state.generation,
                         mixar_ui_begin=lambda **kwargs: True, mixar_ui_end=end)
    monkeypatch.setattr(ownership, "bpy", SimpleNamespace(context=SimpleNamespace(window_manager=wm)))
    monkeypatch.setattr(ownership, "available", lambda: None)
    monkeypatch.setattr(ownership.observe, "main_window", lambda: SimpleNamespace(
        scene=SimpleNamespace(as_pointer=lambda: 20)))
    ownership.forget()
    yield state
    ownership.forget()


def test_expired_transform_still_blocks_scene_scripts(native):
    ownership.begin("controller-a")
    native.modals = 2
    native.generation += 1  # Native timeout or human takeover.
    assert ownership.active()
    with pytest.raises(UIError, match="interrupted UI operation"):
        ownership.release("controller-a", require_settled=True)
    native.modals = 1  # Human finishes or cancels the transform.
    assert not ownership.active()


def test_owner_can_finish_multiple_steps_and_release(native):
    ownership.begin("controller-a")
    native.modals = 2
    ownership.begin("controller-a")
    with pytest.raises(UIError, match="Another connection"):
        ownership.begin("controller-b")
    with pytest.raises(UIError, match="current UI operation"):
        ownership.release("controller-a", require_settled=True)
    native.modals = 1
    ownership.release("controller-a", require_settled=True)
    assert not ownership.active()


def test_disconnect_keeps_modal_fence_until_explicit_ui_recovery(native):
    ownership.begin("controller-a")
    native.modals = 2
    ownership.release("controller-a")
    assert ownership.active()
    ownership.begin("controller-b")  # Fresh observed UI can cancel the modal.
    with pytest.raises(UIError):
        ownership.release("controller-b", require_settled=True)
    native.modals = 1
    ownership.release("controller-b", require_settled=True)
    assert not ownership.active()
