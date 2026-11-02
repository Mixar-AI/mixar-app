# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The memory guard in front of the render worker: a job goes to a worker only
when a second copy of the document fits, and unreadable memory keeps today's
behaviour (the worker). Platform readers are mocked; the host's own readers
are exercised once, unasserted beyond their type."""

import pytest

from mixar.modules.common.render_worker import memory

GB = 1024 ** 3


@pytest.mark.parametrize("resident, available, expected", [
    (2 * GB, 16 * GB, (True, "fits")),
    (2 * GB, int(2.5 * GB), (True, "fits")),             # exactly x1.25
    (2 * GB, int(2.4 * GB), (False, "low_memory")),
    (8 * GB, 64 * GB, (False, "document_too_large")),    # past the threshold
    (None, 16 * GB, (True, "memory_unknown")),
    (2 * GB, None, (True, "memory_unknown")),
])
def test_the_decision(resident, available, expected):
    assert memory.decide(resident, available) == expected


def _platform(monkeypatch, name, resident, available):
    monkeypatch.setattr(memory.sys, "platform", name)
    key = "linux" if name.startswith("linux") else name
    monkeypatch.setitem(memory._READERS, key, (resident, available))


def test_worker_fits_reads_the_platform_and_logs_one_line(monkeypatch):
    _platform(monkeypatch, "darwin", lambda: 6 * GB, lambda: 4 * GB)
    lines = []
    monkeypatch.setattr(memory.logger, "info", lambda *a: lines.append(a[0] % a[1:]))
    assert memory.worker_fits("preview") is False
    assert lines == ["Render worker preview: in-process (low_memory; "
                     "resident 6.00 GB, available 4.00 GB)"]


def test_a_reader_that_raises_reads_as_unknown_and_keeps_the_worker(monkeypatch):
    def broken():
        raise OSError("no procfs")
    _platform(monkeypatch, "linux", broken, lambda: 1)
    assert memory.readings() == (None, 1)
    assert memory.worker_fits("export") is True


def test_zero_reads_as_unknown(monkeypatch):
    _platform(monkeypatch, "win32", lambda: 0, lambda: 8 * GB)
    assert memory.readings() == (None, 8 * GB)


def test_an_unknown_platform_keeps_the_worker(monkeypatch):
    monkeypatch.setattr(memory.sys, "platform", "sunos5")
    assert memory.readings() == (None, None)
    assert memory.worker_fits("preview") is True


def test_linux_procfs_readers(monkeypatch, tmp_path):
    statm, meminfo = tmp_path / "statm", tmp_path / "meminfo"
    statm.write_text("500000 1000 300 1 0 2000 0\n")
    meminfo.write_text("MemTotal:  32000000 kB\nMemFree: 1000 kB\nMemAvailable:  12000000 kB\n")
    real_open = open
    paths = {"/proc/self/statm": str(statm), "/proc/meminfo": str(meminfo)}
    monkeypatch.setattr("builtins.open", lambda path, *a, **k: real_open(paths.get(path, path), *a, **k))
    monkeypatch.setattr(memory.os, "sysconf", lambda name: 4096)
    assert memory._linux_resident() == 1000 * 4096
    assert memory._linux_available() == 12000000 * 1024


def test_the_host_readers_return_bytes_or_none():
    resident, available = memory.readings()
    for value in (resident, available):
        assert value is None or (isinstance(value, int) and value > 0)
