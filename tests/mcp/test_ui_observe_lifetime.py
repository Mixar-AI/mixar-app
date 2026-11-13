# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Observation rejects unsafe reads before accessing RNA or capturing pixels."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from mixar.modules.common.ui_control.core import observe
from mixar.modules.common.ui_control.constants import UIError


def test_worker_cannot_touch_bpy(monkeypatch):
    class NoRNA:
        @property
        def context(self):
            raise AssertionError('off-thread RNA access')
    monkeypatch.setattr(observe, 'bpy', NoRNA())
    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(UIError, match='main thread'):
            pool.submit(observe.widgets).result()


def test_pending_dump_refuses_before_window_or_secret_inventory(monkeypatch):
    wm = SimpleNamespace(mixar_qa_ui_dump='{"pending":true,"widgets":[]}')
    monkeypatch.setattr(observe, 'bpy', SimpleNamespace(context=SimpleNamespace(window_manager=wm)))
    with pytest.raises(UIError, match='redraw'):
        observe.widgets()


def test_settled_dump_still_reads_widgets(monkeypatch):
    wm = SimpleNamespace(mixar_qa_ui_dump='{"pending":false,"widgets":[]}', windows=[])
    monkeypatch.setattr(observe, 'bpy', SimpleNamespace(context=SimpleNamespace(window_manager=wm)))
    assert observe.widgets() == []


def test_native_guard_precedes_all_button_and_provider_access():
    source = (Path(__file__).resolve().parents[2] /
              'src/source/blender/editors/interface/interface_qa_inspect.cc').read_text()
    region = source.split('void qa_dump_region(', 1)[1].split('}  // namespace', 1)[0]
    guard = region.index('region->runtime->do_draw &')
    assert guard < region.index('qa_emit_custom_targets(') < region.index('block.buttons_ptrs')
    for flag in ('RGN_DRAW', 'RGN_DRAW_PARTIAL', 'RGN_DRAWING', 'RGN_REFRESH_UI'):
        assert flag in region[guard:region.index('qa_emit_custom_targets(')]
    assert 'pending = true;' in region
    assert region.index('block_name_map.lookup_default(block.name, nullptr) != &block') < region.index('block.buttons_ptrs')
    assert 'if (!block.active)' not in region


def _dumps(monkeypatch, *pending):
    """widgets() sees one dump per read: pending or settled, the last one repeating."""
    reads = iter(pending)
    state = {"last": pending[-1], "reads": 0}

    class WM:
        windows = ()

        @property
        def mixar_qa_ui_dump(self):
            state["last"] = next(reads, state["last"])
            state["reads"] += 1
            return '{"pending":%s,"widgets":[]}' % ("true" if state["last"] else "false")
    monkeypatch.setattr(observe, 'bpy', SimpleNamespace(context=SimpleNamespace(window_manager=WM())))
    return state


def _drive(gen):
    yields = 0
    while True:
        try:
            next(gen)
            yields += 1
        except StopIteration as done:
            return done.value, yields


def test_settled_reads_again_after_a_pending_redraw(monkeypatch):
    state = _dumps(monkeypatch, True, True, False)
    value, yields = _drive(observe.settled(observe.widgets))
    assert value == [] and yields == 2 and state["reads"] == 3


def test_settled_gives_up_as_not_ready_when_the_redraw_never_lands(monkeypatch):
    _dumps(monkeypatch, True)
    with pytest.raises(observe.Pending) as exc:
        _drive(observe.settled(observe.widgets, timeout=0))
    assert exc.value.code == 'not_ready'


def test_settled_does_not_retry_other_refusals():
    calls = []

    def refuse():
        calls.append(1)
        raise UIError('target_changed', 'observe again')
    with pytest.raises(UIError, match='observe again'):
        _drive(observe.settled(refuse))
    assert len(calls) == 1


def _reads(monkeypatch, *results):
    """observe.widgets() returns each result in turn (Pending = mid-redraw); the last repeats."""
    left = list(results)

    def widgets():
        value = left.pop(0) if len(left) > 1 else left[0]
        if value is observe.Pending:
            raise observe.Pending()
        return value
    monkeypatch.setattr(observe, 'widgets', widgets)


def _request(monkeypatch, name, args):
    from mixar.modules.common.ui_control.core import service
    from mixar.modules.mcp_bridge.core import runtime
    monkeypatch.setattr(runtime, 'ui_control_enabled', lambda: True)
    monkeypatch.setattr(observe, 'main_window', lambda: SimpleNamespace(scene=SimpleNamespace()))
    monkeypatch.setattr(service.ownership, 'settling', lambda: False)
    return service._run(SimpleNamespace(name=name, args=args, session='', owner='o', deadline=float('inf')))


def test_wait_keeps_polling_through_a_pending_redraw(monkeypatch):
    _reads(monkeypatch, observe.Pending, [{'text': 'Render'}])
    gen = _request(monkeypatch, 'mixar_ui_wait', {'query': {'text': 'render'}, 'timeout': 5})
    (result, _), yields = _drive(gen)
    assert result == {'condition_met': True} and yields == 1


def test_wait_for_absence_is_not_met_by_an_unreadable_ui(monkeypatch):
    """Mid-redraw the widget is neither present nor absent, so the wait times out unmet."""
    _reads(monkeypatch, observe.Pending)
    gen = _request(monkeypatch, 'mixar_ui_wait', {'query': {'text': 'render'}, 'present': False, 'timeout': 0})
    (result, _), _ = _drive(gen)
    assert result == {'condition_met': False}


def test_observe_reads_again_instead_of_failing_the_call(monkeypatch):
    answers = [observe.Pending(), ({'targets': []}, [])]

    def fake(owner, args):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer
    monkeypatch.setattr(observe, 'observe', fake)
    (result, _), yields = _drive(_request(monkeypatch, 'mixar_ui_observe', {}))
    assert result == {'targets': []} and yields == 1 and not answers


def test_choose_clicks_the_item_after_the_popup_finishes_drawing(monkeypatch):
    from mixar.modules.common.ui_control.core import input as native
    win = SimpleNamespace(as_pointer=lambda: 7, cursor_warp=lambda *xy: None)
    opener = {'_win': win, 'rect': [0, 0, 10, 10]}
    entry = {'popup': True, 'w': 7, 'text': 'Cube', '_win': win, 'rect': [20, 20, 30, 30]}
    sent = []
    monkeypatch.setattr(observe, 'resolve', lambda owner, context, target: opener)
    monkeypatch.setattr(native, 'point', lambda item: tuple(item['rect'][:2]))
    monkeypatch.setattr(native, 'event', lambda owner, item, key, value, xy, *a, **kw: sent.append((key, value, xy)))
    monkeypatch.setattr(native.ownership, 'begin', lambda owner: None)
    monkeypatch.setattr(native, 'bpy', SimpleNamespace(context=SimpleNamespace(
        window_manager=SimpleNamespace(mixar_ui_pending=lambda: False))))
    _reads(monkeypatch, observe.Pending, observe.Pending, [entry])
    result, _ = _drive(native.run('o', {'context': 'c', 'target': 't0', 'action': 'choose', 'item': 'cube'}))
    assert result['input_delivered'] is True
    assert [xy for key, value, xy in sent if (key, value) == ('LEFTMOUSE', 'PRESS')] == [(0, 0), (20, 20)]


def test_choose_still_refuses_when_the_item_never_appears(monkeypatch):
    from mixar.modules.common.ui_control.core import input as native
    win = SimpleNamespace(as_pointer=lambda: 7, cursor_warp=lambda *xy: None)
    monkeypatch.setattr(observe, 'resolve', lambda owner, context, target: {'_win': win, 'rect': [0, 0, 10, 10]})
    monkeypatch.setattr(native, 'point', lambda item: (0, 0))
    monkeypatch.setattr(native, 'event', lambda *a, **kw: None)
    monkeypatch.setattr(native.ownership, 'begin', lambda owner: None)
    clock = iter(range(0, 1000, 3))
    monkeypatch.setattr(native.time, 'monotonic', lambda: next(clock))
    _reads(monkeypatch, observe.Pending)
    with pytest.raises(UIError, match='unambiguous visible popup item'):
        _drive(native.run('o', {'context': 'c', 'target': 't0', 'action': 'choose', 'item': 'cube'}))
