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
