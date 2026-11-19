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


def test_reconfigure_forgets_library_paths_the_new_release_no_longer_ships(tmp_path):
    """A build directory reused across Blender releases: 5.2's `sycl8.lib` is gone
    from the 5.3 library tree, and the cached find_library() result must go with it."""
    source = tmp_path / "source"
    build = tmp_path / "build"
    libs = tmp_path / "checkout" / "source" / "lib" / "windows_x64"
    (libs / "dpcpp" / "lib").mkdir(parents=True)
    (libs / "dpcpp" / "include").mkdir()
    kept = libs / "dpcpp" / "lib" / "sycl9.lib"
    kept.write_bytes(b"")
    gone = (libs / "dpcpp" / "lib" / "sycl8.lib").as_posix()
    gone_dir = (libs / "embree" / "include").as_posix()
    outside = (tmp_path / "elsewhere" / "tool.exe").as_posix()
    source.mkdir()
    (source / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.16)\n"
        "project(library_cache_recovery NONE)\n"
        "if(SEED_CACHE)\n"
        f'  set(SYCL_LIBRARY "{gone}" CACHE FILEPATH "")\n'
        f'  set(EMBREE_INCLUDE_DIR "{gone_dir}" CACHE PATH "")\n'
        f'  set(SYCL_LIBRARY_KEPT "{kept.as_posix()}" CACHE FILEPATH "")\n'
        f'  set(SYCL_INCLUDE_DIR "{(libs / "dpcpp" / "include").as_posix()}" CACHE PATH "")\n'
        f'  set(USER_TOOL "{outside}" CACHE FILEPATH "")\n'
        '  set(OPTIONAL_LIBRARY "OPTIONAL_LIBRARY-NOTFOUND" CACHE FILEPATH "")\n'
        f'  set(LIB_NOTE "{gone}" CACHE STRING "")\n'
        "else()\n"
        "  foreach(var SYCL_LIBRARY EMBREE_INCLUDE_DIR)\n"
        "    if(DEFINED ${var})\n"
        '      message(FATAL_ERROR "Stale library path survived: ${var}=${${var}}")\n'
        "    endif()\n"
        "  endforeach()\n"
        "endif()\n",
        encoding="utf-8",
    )
    env = dict(os.environ, MIXAR_CUDA="0")
    env.pop("PYTHON_VERSION", None)

    def configure(*args):
        result = subprocess.run(
            [CMAKE, "-S", str(source), "-B", str(build), *args],
            env=env, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout

    configure("-DSEED_CACHE=ON")
    output = configure(
        "-C", str(ROOT / "cmake" / (
            "mixar_overrides.cmake" if os.name == "nt" else "windows_python_cache.cmake"
        )),
        "-DSEED_CACHE=OFF",
    )
    assert "Cleared 2 cached library paths that no longer exist" in output
    cache = (build / "CMakeCache.txt").read_text(encoding="utf-8")
    assert f"SYCL_LIBRARY_KEPT:FILEPATH={kept.as_posix()}" in cache
    assert "SYCL_INCLUDE_DIR:PATH=" in cache
    assert f"USER_TOOL:FILEPATH={outside}" in cache
    assert "OPTIONAL_LIBRARY:FILEPATH=OPTIONAL_LIBRARY-NOTFOUND" in cache
    assert f"LIB_NOTE:STRING={gone}" in cache
    assert "SYCL_LIBRARY:FILEPATH=" not in cache and "EMBREE_INCLUDE_DIR:PATH=" not in cache
