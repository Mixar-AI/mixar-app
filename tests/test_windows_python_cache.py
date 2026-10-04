# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Reconfigure a real CMake cache left by the previous Blender release."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
CMAKE = shutil.which("cmake")
pytestmark = pytest.mark.skipif(CMAKE is None, reason="Requires CMake")


@pytest.mark.parametrize("cached_version, expected_version", [
    ("3.11", "3.13"), ("3.13", "3.13"), ("3.11", None),
])
def test_reconfigure_preserves_objects_and_unrelated_cache(tmp_path, cached_version, expected_version):
    source = tmp_path / "source"
    build = tmp_path / "build with spaces"
    source.mkdir()
    digits = cached_version.replace(".", "")
    (source / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.16)\n"
        "project(cache_recovery NONE)\n"
        "if(SEED_CACHE)\n"
        f'  set(PYTHON_VERSION "{cached_version}" CACHE STRING "")\n'
        f'  set(PYTHON_INCLUDE_DIR "E:/lib/python/{digits}/include" CACHE PATH "")\n'
        f'  set(AUDASPACE_LIB_DEPENDS "general;E:/lib/python/{digits}/libs/python{digits}.lib;" CACHE STRING "")\n'
        f'  set(NUMPY_INCLUDE_DIR [=[E:\\lib\\python\\{digits}\\lib\\numpy]=] CACHE PATH "")\n'
        f'  set(OTHER_PYTHON_LIB "E:/lib/python{cached_version}/libpython.a" CACHE STRING "")\n'
        '  set(KEEP_OPTION "user choice" CACHE STRING "")\n'
        '  set(WITH_PYTHON ON CACHE BOOL "")\n'
        '  set(WITH_CYCLES_DEVICE_CUDA OFF CACHE BOOL "")\n'
        "elseif(EXPECT_CLEAN)\n"
        "  foreach(var PYTHON_VERSION PYTHON_INCLUDE_DIR AUDASPACE_LIB_DEPENDS NUMPY_INCLUDE_DIR OTHER_PYTHON_LIB)\n"
        "    if(DEFINED ${var})\n"
        '      message(FATAL_ERROR "Stale Python cache survived: ${var}")\n'
        "    endif()\n"
        "  endforeach()\n"
        "endif()\n",
        encoding="utf-8",
    )
    env = dict(os.environ, MIXAR_CUDA="0")
    env.pop("PYTHON_VERSION", None)
    if expected_version:
        env["PYTHON_VERSION"] = expected_version
    should_clear = expected_version is not None and cached_version != expected_version

    def configure(*args):
        result = subprocess.run(
            [CMAKE, "-S", str(source), "-B", str(build), *args],
            env=env, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    configure("-DSEED_CACHE=ON")
    marker = build / "existing.obj"
    marker.write_bytes(b"preserve compiled objects")
    configure(
        "-C", str(ROOT / "cmake" / (
            "mixar_overrides.cmake" if os.name == "nt" else "windows_python_cache.cmake"
        )),
        "-DSEED_CACHE=OFF",
        f"-DEXPECT_CLEAN={'ON' if should_clear else 'OFF'}",
    )
    cache = (build / "CMakeCache.txt").read_text(encoding="utf-8")
    assert "KEEP_OPTION:STRING=user choice" in cache
    assert "WITH_PYTHON:BOOL=ON" in cache
    assert "WITH_CYCLES_DEVICE_CUDA:BOOL=OFF" in cache
    assert marker.read_bytes() == b"preserve compiled objects"
    if not should_clear:
        assert f"PYTHON_VERSION:STRING={cached_version}" in cache
        assert f"AUDASPACE_LIB_DEPENDS:STRING=general;E:/lib/python/{digits}/" in cache
