# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Final close codes, the bounded send lanes, and the cached TLS pair."""

from __future__ import annotations

import ast
import os
import stat
import sys
import threading
import time
from pathlib import Path

import pytest

from mixar.modules.virtual_camera import constants
from mixar.modules.virtual_camera.core import connection as connection_mod
from mixar.modules.virtual_camera.core import tls_utils

ROOT = Path(__file__).resolve().parents[2]
VCAM = ROOT / "src/scripts/mixar/modules/virtual_camera"


# ---- final close codes -------------------------------------------------------

def test_close_codes_are_the_4000_to_4003_range():
    assert (
        constants.CLOSE_REPLACED, constants.CLOSE_PAIRING_EXPIRED,
        constants.CLOSE_REPAIRED, constants.CLOSE_SERVER_STOPPED,
    ) == (4000, 4001, 4002, 4003)


def test_new_pairing_closes_with_4002_before_rotating_the_token():
    source = (VCAM / "ui/operators/server_ops.py").read_text(encoding="utf-8")
    body = source.split("class MIXAR_OT_virtual_camera_new_pairing", 1)[1]
    body = body.split("\nclass ", 1)[0]
    drop = body.index('drop_connection(reason="re-pairing", code=CLOSE_REPAIRED)')
    assert drop < body.index("server.state.token = generate_token()")


def test_net_js_stops_on_final_codes_and_backs_off_with_jitter():
    net = (VCAM / "webapp/js/net.js").read_text(encoding="utf-8")
    onclose = net.split("socket.onclose = (e) => {", 1)[1].split("};", 1)[0]
    assert "e.code" in onclose
    assert "isFinalClose(code)" in onclose
    assert "!final" in onclose and "backoffDelay()" in onclose
    assert "setTimeout(connect, 1500)" not in net
    assert "FINAL_CLOSE_MIN = 4000" in net and "FINAL_CLOSE_MAX = 4003" in net
    backoff = net.split("function backoffDelay()", 1)[1].split("\n  }\n", 1)[0]
    assert "Math.random()" in backoff and "BACKOFF_MAX_MS" in backoff
    # A successful open resets the backoff.
    assert "attempts = 0;" in net.split("socket.onopen", 1)[1].split("};", 1)[0]


def test_app_js_asks_for_a_fresh_qr_scan_on_a_final_close():
    app = (VCAM / "webapp/js/app.js").read_text(encoding="utf-8")
    handler = app.split('Net.on("close", (info) => {', 1)[1].split("\n  });", 1)[0]
    assert "info.final" in handler
    assert "gate.classList.remove(\"hidden\")" in handler
    messages = app.split("FINAL_CLOSE_MESSAGES = {", 1)[1].split("};", 1)[0]
    for code in ("4000", "4001", "4002", "4003"):
        assert code in messages
    assert messages.count("QR code") >= 4


# ---- bounded send lanes --------------------------------------------------------

class _BlockedSocket:
    """sendall blocks until released: a phone that stopped reading."""

    def __init__(self):
        self.release = threading.Event()
        self.sent = []

    def sendall(self, data):
        self.release.wait(5)
        self.sent.append(data)

    def shutdown(self, _how):
        pass


def _wait_writer_busy(sock_double, conn):
    deadline = time.time() + 2
    while time.time() < deadline and conn.pending_counts() != (0, 0, 0):
        time.sleep(0.005)


@pytest.fixture
def blocked():
    sock = _BlockedSocket()
    conn = connection_mod.Connection(sock)
    # The writer takes one message and blocks in sendall; everything after
    # stays pending.
    conn.send_json({"t": "toast", "msg": "first"})
    _wait_writer_busy(sock, conn)
    yield sock, conn
    sock.release.set()
    conn.close()


def test_only_the_latest_state_stays_queued(blocked):
    _sock, conn = blocked
    conn.send_json({"t": "state", "frame": 0, "settings": {"stream_fps": 30}})
    for frame in range(1, 1000):
        conn.send_json({"t": "state", "frame": frame})
    assert conn.pending_counts()[1] == 1
    pending = conn._state
    assert pending["frame"] == 999
    # The first sync's settings survive the coalescing.
    assert pending["settings"] == {"stream_fps": 30}


def test_pongs_and_toasts_stay_bounded(blocked):
    _sock, conn = blocked
    for _ in range(1000):
        conn.send_pong(b"x")
        conn.send_json({"t": "toast", "msg": "hi"})
    assert conn.pending_counts()[0] == constants.JSON_QUEUE_MAX


def test_the_writer_drains_queue_then_state_then_frame(blocked):
    sock, conn = blocked
    conn.send_stream_frame(b"jpeg")
    conn.send_json({"t": "state", "frame": 5})
    conn.send_json({"t": "toast", "msg": "later"})
    sock.release.set()
    deadline = time.time() + 2
    while time.time() < deadline and len(sock.sent) < 4:
        time.sleep(0.01)
    kinds = [chunk[0] & 0x0F for chunk in sock.sent]
    assert kinds == [0x1, 0x1, 0x1, 0x2]
    assert b"later" in sock.sent[1] and b'"frame":5' in sock.sent[2]


# ---- TLS pair ------------------------------------------------------------------

@pytest.fixture
def cert_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(tls_utils, "_cache_dir", lambda: str(tmp_path))
    return tmp_path


def _fake_generator(calls):
    def _gen(cert_path, key_path, hosts):
        calls.append((cert_path, key_path, list(hosts)))
        tls_utils._write_private(key_path, b"KEY")
        with open(cert_path, "wb") as fh:
            fh.write(b"CERT " + ",".join(hosts).encode())
        return True
    return _gen


def test_the_key_is_created_0600_and_never_widened(monkeypatch, tmp_path):
    modes = []
    real_open = os.open

    def _spy(path, flags, mode=0o777, *args, **kwargs):
        modes.append(mode)
        return real_open(path, flags, mode, *args, **kwargs)

    monkeypatch.setattr(tls_utils.os, "open", _spy)
    key = tmp_path / "k.key"
    tls_utils._write_private(str(key), b"secret")
    assert modes == [0o600]
    if sys.platform != "win32":
        assert stat.S_IMODE(key.stat().st_mode) == 0o600


def test_generation_happens_in_a_private_folder_and_moves_into_place(cert_dir, monkeypatch):
    calls = []
    monkeypatch.setattr(tls_utils, "_generate_with_cryptography", _fake_generator(calls))
    monkeypatch.setattr(tls_utils, "_pair_loads", lambda c, k: True)
    monkeypatch.setattr(tls_utils, "_san_covers", lambda c, h: True)

    cert, key = tls_utils.ensure_certificate(["10.0.0.2"])
    assert Path(cert).read_bytes() == b"CERT 10.0.0.2"
    tmp_cert, tmp_key, _ = calls[0]
    assert Path(tmp_key).parent != cert_dir  # generated elsewhere...
    assert not Path(tmp_key).parent.exists()  # ...and the work dir is gone
    assert sorted(p.name for p in cert_dir.iterdir()) == sorted(
        [Path(cert).name, Path(key).name]
    )
    if sys.platform != "win32":
        assert stat.S_IMODE(Path(key).stat().st_mode) == 0o600
    # A usable cached pair is reused.
    assert tls_utils.ensure_certificate(["10.0.0.2"]) == (cert, key)
    assert len(calls) == 1


def test_a_cert_missing_the_current_ip_is_regenerated(cert_dir, monkeypatch):
    calls = []
    monkeypatch.setattr(tls_utils, "_generate_with_cryptography", _fake_generator(calls))
    monkeypatch.setattr(tls_utils, "_pair_loads", lambda c, k: True)
    monkeypatch.setattr(
        tls_utils, "_san_covers",
        lambda c, hosts: Path(c).read_bytes() == b"CERT " + hosts[0].encode(),
    )
    tls_utils.ensure_certificate(["10.0.0.2"])
    cert, _ = tls_utils.ensure_certificate(["192.168.1.9"])
    assert len(calls) == 2
    assert Path(cert).read_bytes() == b"CERT 192.168.1.9"


def test_a_pair_that_does_not_load_is_regenerated(cert_dir, monkeypatch):
    calls = []
    monkeypatch.setattr(tls_utils, "_generate_with_cryptography", _fake_generator(calls))
    monkeypatch.setattr(tls_utils, "_san_covers", lambda c, h: True)
    cert_path, key_path = tls_utils.cert_paths()
    Path(cert_path).write_bytes(b"torn")
    Path(key_path).write_bytes(b"mismatched")
    monkeypatch.setattr(tls_utils, "_pair_loads", lambda c, k: False)

    assert tls_utils.ensure_certificate(["10.0.0.2"]) == (cert_path, key_path)
    assert len(calls) == 1
    assert Path(cert_path).read_bytes() == b"CERT 10.0.0.2"


def test_a_real_corrupt_pair_does_not_load():
    # The default loader, no mocks: garbage never passes as a usable pair.
    import tempfile

    with tempfile.TemporaryDirectory() as work:
        cert = os.path.join(work, "c.crt")
        key = os.path.join(work, "c.key")
        Path(cert).write_bytes(b"not a cert")
        Path(key).write_bytes(b"not a key")
        assert tls_utils._pair_loads(cert, key) is False


def test_no_generator_means_no_tls(cert_dir, monkeypatch):
    monkeypatch.setattr(tls_utils, "_generate_with_cryptography", lambda *a: False)
    monkeypatch.setattr(tls_utils, "_generate_with_openssl", lambda *a: False)
    assert tls_utils.ensure_certificate(["10.0.0.2"]) is None
    assert list(cert_dir.iterdir()) == []


def test_the_server_regenerates_once_when_the_pair_will_not_load():
    source = (VCAM / "core/server.py").read_text(encoding="utf-8")
    start = next(
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "start"
    )
    body = ast.unparse(start)
    retry = body.split("except (ssl.SSLError, OSError, ValueError):", 1)[1]
    retry = retry.split("httpd.socket", 1)[0]
    assert "tls_utils.regenerate(hosts)" in retry
    assert retry.count("load_cert_chain") == 1
