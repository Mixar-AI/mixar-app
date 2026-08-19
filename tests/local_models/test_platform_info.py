# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""OS/arch key mapping and failure-tolerant RAM probing."""

import pytest

from mixar.modules.local_models.core import platform_info
from mixar.modules.local_models.constants import RUNTIME_ASSETS


@pytest.mark.parametrize("raw,expected", [
    ("darwin", "mac"),
    ("win32", "windows"),
    ("linux", "linux"),
    ("linux2", "linux"),  # ancient sys.platform spelling still maps
    ("freebsd14", ""),
])
def test_os_key_mapping(raw, expected):
    assert platform_info.os_key(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("arm64", "arm64"),
    ("aarch64", "arm64"),
    ("AArch64", "arm64"),
    ("x86_64", "x64"),
    ("AMD64", "x64"),
    ("i686", ""),
    ("riscv64", ""),
])
def test_arch_key_normalization(raw, expected):
    assert platform_info.arch_key(raw) == expected


def test_platform_key_tuples_cover_runtime_assets():
    """Every asset-map key is producible by the two mappers."""
    for os_name, arch in RUNTIME_ASSETS:
        assert os_name in ("mac", "windows", "linux")
        assert arch in ("arm64", "x64")


def test_total_ram_zero_on_probe_failure(monkeypatch):
    monkeypatch.setattr(platform_info, "os_key", lambda *_: "linux")
    monkeypatch.setattr(
        platform_info, "_ram_linux",
        lambda: (_ for _ in ()).throw(OSError("no sysconf")),
    )
    assert platform_info.total_ram_bytes() == 0


def test_total_ram_zero_on_unknown_platform(monkeypatch):
    monkeypatch.setattr(platform_info, "os_key", lambda *_: "")
    assert platform_info.total_ram_bytes() == 0


def test_total_ram_uses_linux_sysconf(monkeypatch):
    monkeypatch.setattr(platform_info, "os_key", lambda *_: "linux")
    monkeypatch.setattr(platform_info, "_ram_linux", lambda: 16 * 1024 ** 3)
    assert platform_info.total_ram_bytes() == 16 * 1024 ** 3


def test_total_ram_mac_parses_sysctl(monkeypatch):
    monkeypatch.setattr(platform_info, "os_key", lambda *_: "mac")
    monkeypatch.setattr(platform_info, "_ram_mac", lambda: 34359738368)
    assert platform_info.total_ram_bytes() == 34359738368
