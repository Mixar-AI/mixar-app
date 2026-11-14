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


def test_windows_skipped_from_drawing_never_hold_the_dump_pending():
    """The island resting as a pill is never drawn, so its redraw tags never
    clear: the dump must skip it with the exact predicate drawing uses."""
    root = Path(__file__).resolve().parents[2] / 'src/source/blender'
    dump = (root / 'editors/interface/interface_qa_inspect.cc').read_text()
    body = dump.split('std::string Mixar_ui_qa_inspect_json(', 1)[1]
    skip = body.index('Mixar_window_draw_skipped(win)')
    assert skip < body.index('qa_dump_region(')
    draw = (root / 'windowmanager/intern/wm_draw.cc').read_text()
    loop = draw.split('void wm_draw_update(bContext *C)', 1)[1]
    assert loop.index('Mixar_window_draw_skipped(&win)') < loop.index('wm_draw_window(C, &win)')
    predicate = draw.split('bool Mixar_window_draw_skipped(const wmWindow *win)', 1)[1].split('\n}\n', 1)[0]
    for check in ('GHOST_kWindowStateMinimized', 'ED_agent_bubble_is_minimised_window(win)',
                  'Mixar_WindowIsVisible(win->runtime->ghostwin)'):
        assert check in predicate
    # Only drawing decides: no second copy of the hidden-window checks.
    assert 'Mixar_WindowIsVisible' not in loop
    assert 'ED_agent_bubble_is_minimised_window' not in loop


def test_inventory_reports_windows_mixar_does_not_draw(monkeypatch):
    dump = ('{"pending":false,"widgets":[],"windows":[{"ptr":1,"skipped":true,"pending":false},'
            '{"ptr":2,"skipped":false,"pending":false}]}')
    wm = SimpleNamespace(mixar_qa_ui_dump=dump, windows=[])
    monkeypatch.setattr(observe, 'bpy', SimpleNamespace(context=SimpleNamespace(window_manager=wm)))
    assert observe.inventory() == ([], {1})


def test_hidden_window_is_never_captured_without_its_password_masks():
    """A skipped window exports no widgets, so no secret masks: refuse before capturing."""
    def capture(filepath):
        raise AssertionError('captured a window that has no mask inventory')
    win = SimpleNamespace(as_pointer=lambda: 1, mixar_ui_capture=capture)
    with pytest.raises(UIError) as exc:
        observe.image(win, [], {1})
    assert exc.value.code == 'capture_unavailable'


def _window(ptr, scene='S'):
    region = SimpleNamespace(x=0, y=0, width=10, height=10, type='WINDOW')
    area = SimpleNamespace(regions=[region], type='VIEW_3D', x=0, y=0, width=10, height=10)
    return SimpleNamespace(as_pointer=lambda: ptr, screen=SimpleNamespace(areas=[area]),
                           global_areas=[], scene=SimpleNamespace(name=scene, mixie_session_id='s'))


@pytest.mark.parametrize('skipped', [False, True])
def test_region_act_resolves_in_a_pending_dump_unless_its_window_is_hidden(monkeypatch, skipped):
    """A viewport redrawing every frame keeps the dump pending; a region act
    needs no widget inventory, so only a hidden window refuses it."""
    win = _window(1)
    dump = ('{"pending":true,"widgets":[],"windows":[{"ptr":1,"skipped":%s,"pending":true}]}'
            % ('true' if skipped else 'false'))
    monkeypatch.setattr(observe, 'bpy', SimpleNamespace(context=SimpleNamespace(
        window_manager=SimpleNamespace(windows=[win], mixar_qa_ui_dump=dump))))
    monkeypatch.setattr(observe, 'signature', lambda: 'sig')
    monkeypatch.setattr(observe, 'region_identity', lambda *_: 'rid')
    monkeypatch.setitem(observe._contexts, 'ctx', {
        'owner': 'o', 'expires': float('inf'), 'signature': 'sig', 'targets': {'r0': ('region', 'rid')}})
    if skipped:
        with pytest.raises(UIError) as exc:
            observe.resolve('o', 'ctx', 'r0')
        assert exc.value.code == 'window_unavailable'
    else:
        assert observe.resolve('o', 'ctx', 'r0')['_win'] is win


def test_observe_lists_no_regions_of_a_hidden_window(monkeypatch):
    shown, hidden = _window(2), _window(1)
    monkeypatch.setattr(observe, 'bpy', SimpleNamespace(context=SimpleNamespace(
        window_manager=SimpleNamespace(windows=[hidden, shown]))))
    monkeypatch.setattr(observe, 'main_window', lambda: shown)
    monkeypatch.setattr(observe, 'signature', lambda: 'sig')
    monkeypatch.setattr(observe, 'region_identity', lambda win, *_: win.as_pointer())
    monkeypatch.setattr(observe, 'inventory', lambda: ([], {1}))
    result, blocks = observe.observe('o', {})
    assert [r['window'] for r in result['regions']] == ['w1'] and blocks == []
    targets = observe._contexts[result['context']]['targets']
    assert [identity for kind, identity in targets.values() if kind == 'region'] == [2]


def test_dump_reports_skipped_and_pending_per_window():
    source = (Path(__file__).resolve().parents[2] /
              'src/source/blender/editors/interface/interface_qa_inspect.cc').read_text()
    body = source.split('std::string Mixar_ui_qa_inspect_json(', 1)[1]
    assert '\\"skipped\\":' in body and '\\"pending\\":' in body
    assert body.index('if (!skipped)') < body.index('qa_dump_region(')
