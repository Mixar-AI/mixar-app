# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Every agent socket says how it ended, once, and the report reaches the server.

Prod 2026-10-14: 53 % of agent sockets ended half-open and the server could
only see silence. The writer thread's send failures were swallowed without a
line, so a frame that outlived the 10 s socket timeout looked like a dead
network. Each ending now records its reason and rides on the next handshake.
"""
import threading
from types import SimpleNamespace

import pytest

from mixar.modules.space_mixie_chat.core.socket_diagnostics import SocketDiagnostics


def test_first_reason_wins_and_is_reported_once():
    diag = SocketDiagnostics()
    first = diag.begin()
    diag.phase('connected')
    diag.received(120)
    diag.end('receive_error', OSError(9, 'Bad file descriptor'))
    diag.end('receive_loop_exit')  # the run loop's catch-all must not overwrite it
    (report,) = diag.pending_reports()
    assert report['socket_seq'] == first.seq and report['reason'] == 'receive_error'
    assert report['exception'] == 'OSError' and 'Bad file descriptor' in report['message']
    assert report['phase'] == 'connected' and report['received'] == 1

    second = diag.begin()
    assert second.seq == first.seq + 1
    diag.acknowledge([report])
    assert diag.pending_reports() == []


def test_a_send_in_flight_is_part_of_the_verdict():
    diag = SocketDiagnostics()
    diag.begin()
    diag.send_starting(12_000_000)
    diag.end('writer_error', TimeoutError('The write operation timed out'), send_bytes=12_000_000)
    (report,) = diag.pending_reports()
    assert report['in_flight_send_bytes'] == 12_000_000
    assert report['in_flight_send_s'] >= 0


def test_no_local_path_or_unbounded_text_leaves_the_machine():
    diag = SocketDiagnostics()
    diag.begin()
    diag.end('receive_error', FileNotFoundError('/Users/alice/secret/x.blend ' + 'y' * 2000))
    (report,) = diag.pending_reports()
    assert '/Users/alice' not in report['message'] and '<path>' in report['message']
    assert len(report['message']) <= 300


def test_the_writer_no_longer_drops_a_socket_silently(monkeypatch):
    from queue import Queue
    from mixar.modules.space_mixie_chat.core import socket_writer

    class _Socket:
        closed = False
        def gettimeout(self): return 10.0
        def send(self, frame): raise TimeoutError('The write operation timed out')
        def close(self): self.closed = True

    sock = _Socket()
    outbound = Queue()
    outbound.put('x' * 1000)
    client = SimpleNamespace(_ws=sock, _running=threading.Event(), _outbound=outbound,
                             _connected=True, _expire_pending=lambda: None,
                             _diag=SocketDiagnostics())
    client._running.set()
    client._diag.begin()
    stopped, thread = socket_writer.start_writer(client)
    thread.join(2)
    stopped.set()
    (report,) = client._diag.pending_reports()
    assert report['reason'] == 'writer_error' and report['send_bytes'] == 1000
    assert report['socket_timeout_s'] == 10.0 and sock.closed and client._connected is False


class _SlicedSocket:
    """A websocket-client socket whose writes each take one slice, or stall."""

    def __init__(self, stall=False):
        self.lock = threading.Lock()
        self.get_mask_key = None
        self.whole, self.slices, self.stall = [], [], stall

    def send(self, frame):
        self.whole.append(frame)

    def _send(self, data):
        if self.stall:
            return 0
        self.slices.append(len(data))
        return len(data)


@pytest.fixture
def real_websocket(monkeypatch):
    """Other test modules leave a MagicMock in sys.modules['websocket']; the
    slicing tests need the real ABNF framing."""
    import sys
    for name in [n for n in sys.modules if n == 'websocket' or n.startswith('websocket.')]:
        monkeypatch.delitem(sys.modules, name)
    return pytest.importorskip('websocket')


def _writer_client():
    client = SimpleNamespace(_diag=SocketDiagnostics(), _last_send_progress=0.0)
    client._diag.begin()
    return client


def test_a_large_frame_leaves_in_slices_each_with_its_own_timeout(real_websocket):
    """Prod 2026-10-18..20: 181 sockets died at exactly the 10 s socket timeout
    with a ~1 MB frame in flight — one TLS write of the whole frame had to beat
    the timeout. Each 64 KB slice now gets its own."""
    from mixar.modules.space_mixie_chat.core import socket_writer

    client, sock = _writer_client(), _SlicedSocket()
    client._diag.send_starting(1_000_000)
    socket_writer._send(client, sock, 'x' * 1_000_000)
    assert sock.whole == [] and len(sock.slices) > 10
    assert max(sock.slices) == socket_writer._SLICE
    assert sum(sock.slices) > 1_000_000  # the frame header and mask ride along
    assert client._diag.current.send_done == sum(sock.slices)
    assert client._last_send_progress > 0  # a moving upload holds the liveness probe off

    small = _SlicedSocket()
    socket_writer._send(client, small, '{"id": 1}')
    assert small.whole == ['{"id": 1}'] and small.slices == []


def test_an_upload_that_stops_moving_still_times_out(real_websocket):
    from mixar.modules.space_mixie_chat.core import socket_writer

    WebSocketTimeoutException = real_websocket.WebSocketTimeoutException

    client = _writer_client()
    try:
        socket_writer._send(client, _SlicedSocket(stall=True), 'x' * 200_000)
    except WebSocketTimeoutException:
        pass
    else:
        raise AssertionError("a stalled slice must fail the send")


def test_the_report_says_how_far_the_frame_got():
    diag = SocketDiagnostics()
    diag.begin()
    diag.send_starting(1_000_000)
    diag.send_progress(393_216)
    diag.end('writer_error', TimeoutError('The write operation timed out'))
    (report,) = diag.pending_reports()
    assert report['in_flight_send_bytes'] == 1_000_000
    assert report['in_flight_sent_bytes'] == 393_216


def test_a_sleeping_machine_is_named(monkeypatch):
    """macOS: the monotonic clock stops while the lid is shut, the wall clock
    does not. A reset seen on wake is the sleep, not the network."""
    from mixar.modules.space_mixie_chat.core import socket_diagnostics as sd

    wall = [1000.0]
    monkeypatch.setattr(sd.time, 'time', lambda: wall[0])
    diag = SocketDiagnostics()
    diag.begin()
    wall[0] += 900.0  # 15 min of wall time, ~0 monotonic
    diag.end('receive_error', ConnectionResetError(54, 'Connection reset by peer'))
    (report,) = diag.pending_reports()
    assert report['slept_s'] >= 899 and report['errno'] == 54
    assert report['ended_at'] == 1900.0


def test_windows_stale_errno_is_kept_for_the_server_to_read():
    diag = SocketDiagnostics()
    diag.begin()
    exc = FileNotFoundError(2, 'No such file or directory')
    diag.end('receive_error', exc)
    (report,) = diag.pending_reports()
    assert report['exception'] == 'FileNotFoundError' and report['errno'] == 2
    assert 'slept_s' not in report


def test_the_handshake_says_how_this_socket_came_to_be():
    diag = SocketDiagnostics()
    diag.begin()
    diag.end('connection_lost')
    diag.begin(attempt=2, waited_s=4.04)
    info = diag.reconnect()
    assert info['attempt'] == 2 and info['waited_s'] == 4.04
    assert info['previous_seq'] == 1 and info['previous_reason'] == 'connection_lost'
    assert info['after_s'] >= 0


def test_an_app_that_died_connected_is_reported_on_the_next_launch(tmp_path, monkeypatch):
    from mixar.modules.space_mixie_chat.core import socket_diagnostics as sd

    old = SocketDiagnostics(instance_id='inst-old', state_dir=str(tmp_path))
    old.begin()
    old.phase('connected')  # writes this run's state file
    (state_file,) = list(tmp_path.iterdir())
    monkeypatch.setattr(sd.os, 'getpid', lambda: 999_999)  # the next launch
    later = sd.time.time() + sd._STALE_S + 60
    monkeypatch.setattr(sd.time, 'time', lambda: later)

    new = SocketDiagnostics(instance_id='inst-new', state_dir=str(tmp_path))
    (report,) = new.pending_reports()
    assert report['reason'] == 'app_exited' and report['instance_id'] == 'inst-old'
    assert report['down_s'] >= sd._STALE_S and not state_file.exists()
    new.acknowledge([report])
    assert new.pending_reports() == []


def test_a_clean_stop_or_a_running_neighbour_reports_nothing(tmp_path, monkeypatch):
    from mixar.modules.space_mixie_chat.core import socket_diagnostics as sd

    stopped = SocketDiagnostics(instance_id='inst-a', state_dir=str(tmp_path))
    stopped.begin()
    stopped.phase('connected')
    stopped.end('client_stopped')
    assert list(tmp_path.iterdir()) == []

    running = SocketDiagnostics(instance_id='inst-b', state_dir=str(tmp_path))
    running.begin()
    running.phase('connected')  # fresh: another Mixar still running
    monkeypatch.setattr(sd.os, 'getpid', lambda: 999_998)
    assert SocketDiagnostics(instance_id='inst-c', state_dir=str(tmp_path)).pending_reports() == []


def test_an_app_offline_for_long_never_reads_as_dead(tmp_path, monkeypatch):
    """The state file lives only while connected: a running app that lost its
    socket and stayed offline must not be reported by a second Mixar."""
    from mixar.modules.space_mixie_chat.core import socket_diagnostics as sd

    offline = SocketDiagnostics(instance_id='inst-offline', state_dir=str(tmp_path))
    offline.begin()
    offline.phase('connected')
    offline.end('connection_lost')
    offline.begin(attempt=1)
    offline.end('connect_failed', OSError('offline'))
    assert list(tmp_path.iterdir()) == []
    monkeypatch.setattr(sd.os, 'getpid', lambda: 999_997)
    monkeypatch.setattr(sd.time, 'time', lambda: 10 ** 10)
    assert SocketDiagnostics(instance_id='inst-x', state_dir=str(tmp_path)).pending_reports() == []
