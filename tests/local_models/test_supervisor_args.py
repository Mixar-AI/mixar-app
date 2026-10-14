# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Supervisor pure helpers: argv construction + port reuse-else-new."""

import pytest

from mixar.modules.local_models.constants import DEFAULT_CTX_SIZE, PORT_RANGE
from mixar.modules.local_models.core import server_supervisor as sup


def test_argv_without_mmproj():
    argv = sup.build_server_argv(
        "/opt/rt/llama-server", "/models/m.gguf", 11500, "tok123",
    )
    assert argv == [
        "/opt/rt/llama-server",
        "-m", "/models/m.gguf",
        "--host", "127.0.0.1",
        "--port", "11500",
        "--no-webui",
        "--api-key", "tok123",
        "-ngl", "99",
        "-c", str(DEFAULT_CTX_SIZE),
    ]


def test_argv_with_mmproj():
    argv = sup.build_server_argv(
        "/opt/rt/llama-server", "/models/m.gguf", 11501, "tok",
        mmproj_path="/models/mmproj-F16.gguf",
    )
    assert argv[-2:] == ["--mmproj", "/models/mmproj-F16.gguf"]
    assert "--no-webui" in argv
    # --mmproj never appears when the model has none.
    assert "--mmproj" not in sup.build_server_argv(
        "/opt/rt/llama-server", "/models/m.gguf", 11501, "tok",
    )


def test_argv_custom_ctx_size():
    argv = sup.build_server_argv(
        "/bin/llama-server", "/m.gguf", 11500, "t", ctx_size=4096,
    )
    assert argv[argv.index("-c") + 1] == "4096"


def test_choose_port_reuses_free_preferred(monkeypatch):
    monkeypatch.setattr(sup, "_port_is_free", lambda port: True)
    assert sup.choose_port(11542) == 11542


def test_choose_port_picks_new_when_preferred_busy(monkeypatch):
    busy = {11542}
    monkeypatch.setattr(sup, "_port_is_free", lambda port: port not in busy)
    port = sup.choose_port(11542)
    assert port == PORT_RANGE[0]
    assert port != 11542


def test_choose_port_ignores_out_of_range_preferred(monkeypatch):
    monkeypatch.setattr(sup, "_port_is_free", lambda port: True)
    assert PORT_RANGE[0] <= sup.choose_port(8080) <= PORT_RANGE[1]


def test_choose_port_scans_range_in_order(monkeypatch):
    free = {11503}
    monkeypatch.setattr(sup, "_port_is_free", lambda port: port in free)
    assert sup.choose_port(None) == 11503


def test_choose_port_raises_when_exhausted(monkeypatch):
    monkeypatch.setattr(sup, "_port_is_free", lambda port: False)
    with pytest.raises(sup.LocalServerError):
        sup.choose_port(11500)


def test_popen_kwargs_isolate_process_group():
    kwargs = sup._popen_kwargs(None)
    assert kwargs["close_fds"] is True
    import os
    if os.name == "nt":
        assert kwargs["creationflags"]
    else:
        assert kwargs["start_new_session"] is True
