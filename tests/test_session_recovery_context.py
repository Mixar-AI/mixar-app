# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Recovery must not enter native file reading after failed window cleanup
(backend#1914): the shared read-window guard, and the restore flow through it."""
import sys
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, Mock

import pytest

from mixar.modules.agent_bubble.core import bubble_windows
from mixar.modules.session_recovery import journal

NOW = 1_800_000_000.0


def window(*, temporary=False, kind='VIEW_3D', screen=True):
    if not screen:
        return NS(screen=None)
    return NS(screen=NS(is_temporary=temporary, areas=[NS(type=kind)]))


@pytest.fixture
def context(monkeypatch):
    wm = NS(windows=[])
    monkeypatch.setattr(bubble_windows.bpy.context, 'window_manager', wm, raising=False)
    purge = Mock()
    monkeypatch.setitem(sys.modules,
        "mixar.modules.agent_bubble.core.bubble_lifecycle",
        NS(close_restored_agent_bubble_windows=purge))
    return wm, purge


# ---------------------------------------------------------------- the guard --

def test_selects_the_document_window_after_the_purge(context):
    wm, purge = context
    fresh = window()
    wm.windows = [window(kind='AGENT_BUBBLE', temporary=True)]
    purge.side_effect = lambda: setattr(wm, 'windows', [window(temporary=True), fresh])
    assert bubble_windows.prepare_file_read_window() is fresh


def test_a_window_without_a_screen_is_skipped_not_fatal(context):
    wm, _ = context
    main = window()
    wm.windows = [window(screen=False), main]
    assert bubble_windows.prepare_file_read_window() is main


def test_the_pill_is_never_the_document_window(context):
    wm, _ = context
    pill = window(kind='AGENT_BUBBLE')            # the pill's screen is not temporary
    main = window()
    wm.windows = [pill, main]
    assert bubble_windows.document_window(wm) is main


@pytest.mark.parametrize('windows, reason', [
    ([], 'no_document_window'),
    ([window(temporary=True)], 'no_document_window'),
    ([window(screen=False)], 'no_document_window'),
    ([window(), window(kind='AGENT_BUBBLE', temporary=True)], 'bubble_open'),
    ([window(), window(kind='AGENT_BUBBLE')], 'bubble_open'),
])
def test_refuses_incomplete_cleanup_or_context(context, windows, reason):
    wm, purge = context
    wm.windows = windows
    with pytest.raises(bubble_windows.FileReadContextError) as raised:
        bubble_windows.prepare_file_read_window()
    assert raised.value.reason == reason
    purge.assert_called_once()


def test_purge_exception_is_not_swallowed(context):
    wm, purge = context
    wm.windows = [window()]
    purge.side_effect = ReferenceError('removed window')
    with pytest.raises(ReferenceError):
        bubble_windows.prepare_file_read_window()


# ------------------------------------------------------- the restore flow --

@pytest.fixture
def restore(tmp_path, monkeypatch, context):
    """_restore_now over the REAL guard; only the native ops are mocked."""
    from mixar.modules.session_recovery import runtime
    jr = journal.Journal(str(tmp_path / "recovery"), pid=4242, now=NOW)
    monkeypatch.setitem(runtime._state, "journal", jr)
    monkeypatch.setitem(runtime._state, "scheduler", None)
    monkeypatch.setitem(runtime._state, "decided", True)
    monkeypatch.setattr(runtime.bpy.app.timers, "register",
                        lambda fn, first_interval=0, persistent=False: None, raising=False)
    tracked, reported = [], []
    monkeypatch.setattr(runtime.telemetry, "track",
                        lambda stage, offer, **props: tracked.append((stage, props)))
    monkeypatch.setattr(runtime, "_report", reported.append)
    override = MagicMock()
    monkeypatch.setattr(runtime.bpy.context, "temp_override", override, raising=False)
    point = tmp_path / 'recover.mixar'
    point.write_bytes(b'fixture')

    def run(kind='save_point'):
        monkeypatch.setitem(runtime._state, 'offer', {'session': 'old', 'target': {
            'kind': kind, 'path': str(point), 'at': NOW}})
        runtime._restore_now()
    return NS(rt=runtime, run=run, wm=context[0], purge=context[1], point=point,
              tracked=tracked, reported=reported, override=override)


def test_the_read_runs_in_the_window_chosen_after_the_purge(restore, monkeypatch):
    fresh = window()
    restore.wm.windows = [window(kind='AGENT_BUBBLE'), window()]
    restore.purge.side_effect = lambda: setattr(restore.wm, 'windows', [window(screen=False), fresh])
    read = Mock(return_value={'FINISHED'})
    monkeypatch.setattr(restore.rt.bpy.ops.wm, 'recover_auto_save', read, raising=False)
    restore.run()
    read.assert_called_once()
    assert restore.override.call_args.kwargs == {'window': fresh}
    assert restore.tracked[-1][0] == 'scene_restored'


@pytest.mark.parametrize('kind', ['project', 'save_point'])
@pytest.mark.parametrize('windows, message', [
    ([window(), window(kind='AGENT_BUBBLE')], 'Close the Agent island'),
    ([window(temporary=True)], 'could not open the saved work'),
])
def test_a_refused_context_never_reads_and_keeps_the_offer(restore, monkeypatch, kind, windows, message):
    restore.wm.windows = windows
    read = Mock()
    monkeypatch.setattr(restore.rt.bpy.ops.wm, 'open_mainfile', read, raising=False)
    monkeypatch.setattr(restore.rt.bpy.ops.wm, 'recover_auto_save', read, raising=False)
    restore.run(kind)
    read.assert_not_called()
    assert restore.tracked == [('failed', {'surface': restore.rt._state['surface'],
                                           'failure_category': 'context_unavailable'})]
    assert len(restore.reported) == 1 and message in restore.reported[0]
    assert restore.point.exists() and restore.rt.current_offer() is not None
    assert restore.rt._state['restoring'] is False
    assert restore.rt._state['journal'].data['restore_attempt'] is None


def test_a_failing_purge_is_a_refusal_not_a_read_error(restore, monkeypatch):
    restore.wm.windows = [window()]
    restore.purge.side_effect = ReferenceError('removed window')
    read = Mock()
    monkeypatch.setattr(restore.rt.bpy.ops.wm, 'recover_auto_save', read, raising=False)
    restore.run()
    read.assert_not_called()
    assert restore.tracked[-1][1]['failure_category'] == 'context_unavailable'


def test_a_native_read_failure_stays_a_read_error(restore, monkeypatch):
    restore.wm.windows = [window()]
    monkeypatch.setattr(restore.rt.bpy.ops.wm, 'recover_auto_save',
                        Mock(side_effect=RuntimeError('read failed')), raising=False)
    restore.run()
    assert restore.tracked[-1][1]['failure_category'] == 'read_error'


def test_context_unavailable_is_an_allowlisted_failure_category():
    from mixar.modules.common.analytics import recovery_events as RE
    assert 'context_unavailable' in RE.FAILURE_CATEGORIES
