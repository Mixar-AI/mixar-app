# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The native SSO callback server runs before Blender initialises (on the
main thread on macOS and Linux), so a peer that connects and stays silent
must never hang app launch, and a peer that disconnects mid-response must
never kill the process with SIGPIPE (Python has not ignored it yet). On
Windows the listener claims its port exclusively so no other process can
bind it and receive the callback."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/source/creator/mixar_local_auth_server.cc"


def _code() -> str:
    text = SOURCE.read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?<![:\"])//[^\n]*", "", text)


def _body(code: str, signature: str) -> str:
    start = code.index(signature)
    return code[start : code.index("\n}\n", start)]


def test_client_timeouts_cover_both_platforms_and_never_mean_forever():
    fn = _body(_code(), "static void set_client_timeouts(")
    assert "SO_RCVTIMEO" in fn and "SO_SNDTIMEO" in fn
    assert "DWORD timeout = (DWORD)remaining_ms;" in fn          # Windows: milliseconds
    assert "struct timeval timeout;" in fn                       # POSIX: timeval
    assert "if (remaining_ms < 1) remaining_ms = 1;" in fn       # 0 would block forever


def test_accepted_socket_gets_a_budget_before_the_first_recv():
    fn = _body(_code(), "bool auth_server_wait_for_code(")
    accept = fn.index("accept(listen_socket")
    first_recv = fn.index("recv_request_head(")
    budget = fn.index("set_client_timeouts(client_socket")
    assert accept < budget < first_recv
    assert "CLIENT_BUDGET_MS" in fn[accept:first_recv]
    # The budget is clamped to what is left of the 120 s deadline.
    assert "deadline_ms - accepted_ms" in fn
    # The single-shot recv is gone; the response honours the same budget.
    assert "recv(client_socket" not in fn
    assert "send_http_response(client_socket, result, client_deadline_ms)" in fn


def test_request_head_is_read_in_a_bounded_loop():
    fn = _body(_code(), "static int recv_request_head(")
    assert "while (total < size - 1)" in fn
    assert 'strstr(buffer, "\\r\\n\\r\\n")' in fn
    assert "if (remaining_ms <= 0) return -1;" in fn             # total budget, not per-recv
    assert "set_client_timeouts(socket, remaining_ms)" in fn
    assert "EINTR" in fn


def test_send_checks_the_budget_and_never_raises_sigpipe():
    code = _code()
    fn = _body(code, "static bool send_all(")
    assert "if (remaining_ms <= 0) return false;" in fn
    assert "send(socket, data, length, MIXAR_SEND_FLAGS)" in fn
    assert re.search(r"#if defined\(MSG_NOSIGNAL\) && !defined\(__APPLE__\)\n"
                     r"#define MIXAR_SEND_FLAGS MSG_NOSIGNAL", code)
    wait = _body(code, "bool auth_server_wait_for_code(")
    assert re.search(r"#ifdef SO_NOSIGPIPE\s+int no_sigpipe = 1;\s+setsockopt\(client_socket, "
                     r"SOL_SOCKET, SO_NOSIGPIPE", wait)


def test_windows_listener_is_exclusive_and_posix_keeps_reuseaddr():
    fn = _body(_code(), "intptr_t auth_server_start(")
    block = re.search(r"#ifdef _WIN32\n(.*?)#else\n(.*?)#endif", fn[fn.index("int opt = 1;"):], re.S)
    assert block, "listener options must be split per platform"
    windows, posix = block.group(1), block.group(2)
    assert "SO_EXCLUSIVEADDRUSE" in windows and "SO_REUSEADDR" not in windows.replace(
        "SO_EXCLUSIVEADDRUSE", "")
    assert "SO_REUSEADDR" in posix
    assert fn.index("SO_EXCLUSIVEADDRUSE") < fn.index("bind(listen_socket")


def test_the_file_stays_under_the_line_limit():
    assert len(SOURCE.read_text(encoding="utf-8").splitlines()) <= 500
