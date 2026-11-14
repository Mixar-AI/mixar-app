# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""The QA model-card helper reads "shut" only from a settled UI dump.

The dump omits regions awaiting a redraw, custom card targets included. A
single pending sample read as "shut" made open_popup click the chip again and
close the card it had just opened (KEY-13).
"""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

PATH = Path(__file__).resolve().parents[1] / 'qa' / 'model_popup.py'


@pytest.fixture
def mp(monkeypatch):
    spec = importlib.util.spec_from_file_location('qa_model_popup_under_test', PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.time, 'sleep', lambda _s: None)
    return module


class FakeQA:
    """Answers the card-state eval from a script; records chip clicks."""

    def __init__(self, states):
        self.states = list(states)
        self.clicks = 0

    def eval(self, code):
        assert 'mixar_qa_ui_dump' in code and "'pending'" in code
        return self.states.pop(0) if len(self.states) > 1 else self.states[0]

    def click(self, **query):
        self.clicks += 1

    def wait(self, expr, timeout):
        raise AssertionError('open_popup should have seen the card')


def test_pending_sample_is_not_read_as_shut(mp):
    assert mp.is_open(FakeQA([None, None, True])) is True
    assert mp.is_open(FakeQA([None, False])) is False


def test_open_popup_does_not_reclick_an_open_card_hidden_by_a_redraw(mp):
    # close_popup: settled shut; after the click: one pending sample, then open.
    qa = FakeQA([False, None, True])
    mp.open_popup(qa)
    assert qa.clicks == 1


def test_dump_that_never_settles_fails_loudly(mp):
    with pytest.raises(AssertionError, match='pending'):
        mp.is_open(FakeQA([None]), timeout=0)


def test_expressions_distinguish_pending_from_shut(mp):
    assert mp.OPEN.endswith('is True') and mp.SHUT.endswith('is False')
    assert mp.STATE in mp.OPEN and mp.STATE in mp.SHUT


def _window(ptr, area_type):
    area = SimpleNamespace(type=area_type)
    return SimpleNamespace(as_pointer=lambda: ptr, screen=SimpleNamespace(areas=[area]))


@pytest.mark.parametrize('windows,card,expected', [
    # A main window that redraws every frame (rendered viewport) never matters.
    ([{'ptr': 1, 'pending': True}, {'ptr': 2, 'pending': False}], True, True),
    ([{'ptr': 1, 'pending': True}, {'ptr': 2, 'pending': False}], False, False),
    # The island itself awaiting a redraw: card state unknown.
    ([{'ptr': 1, 'pending': False}, {'ptr': 2, 'pending': True}], False, None),
])
def test_state_reads_one_dump_and_only_the_island_windows(mp, windows, card, expected):
    reads = []
    dump = {'pending': any(w['pending'] for w in windows), 'windows': windows,
            'widgets': [{'surface': 'model_card'}] if card else []}

    class WM:
        windows = [_window(1, 'VIEW_3D'), _window(2, 'AGENT_BUBBLE')]

        @property
        def mixar_qa_ui_dump(self):
            reads.append(1)
            return json.dumps(dump)
    bpy = SimpleNamespace(data=SimpleNamespace(window_managers=[WM()]))
    assert eval(mp.STATE, {'bpy': bpy, 'drv': None}) is expected
    assert len(reads) == 1


def test_state_falls_back_to_the_dump_wide_flag_on_older_builds(mp):
    dump = {'pending': True, 'windows': [{'ptr': 2}], 'widgets': []}
    wm = SimpleNamespace(windows=[_window(2, 'AGENT_BUBBLE')], mixar_qa_ui_dump=json.dumps(dump))
    bpy = SimpleNamespace(data=SimpleNamespace(window_managers=[wm]))
    assert eval(mp.STATE, {'bpy': bpy, 'drv': None}) is None
