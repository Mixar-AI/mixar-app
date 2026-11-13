# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""The install directory is read-only at runtime: no bytecode is written into it.

Python wrote `__pycache__` beside the bundled sources, which breaks the signed
macOS bundle's code signature; Gatekeeper then refuses to open the app
("Mixar is damaged", issue #2058). The app's Python caches bytecode per user
(`PyConfig.pycache_prefix`), child Pythons inherit that cache, and the build
ships no `.pyc` (with a prefix set they are never read). The running-app check
is the harness release case that snapshots the bundle around a launch.
"""

import importlib.util
import os
import re
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
INTERN = ROOT / "src/source/blender/python/intern"
UPSTREAM_INTERN = ROOT / "upstream/source/blender/python/intern"
HEADER = INTERN / "bpy_mixar_pycache.hh"

INTERFACE_HUNKS = (
    '#include "bpy_mixar_pycache.hh" /* MIXAR: bytecode cache outside the install directory. */\n',
    "    /* MIXAR: the install directory is read-only at runtime (a written `__pycache__` breaks the\n"
    "     * signed macOS bundle), so bytecode goes to the per-user cache. */\n"
    "    status = bpy_mixar_pycache_config(&config);\n"
    "    pystatus_exit_on_error(status);\n\n",
)
APP_HUNKS = (
    '#include "bpy_mixar_pycache.hh" /* MIXAR: child Pythons share the bytecode cache. */\n',
    "  /* MIXAR: `-I` hides `PYTHONPYCACHEPREFIX`, so name the cache (never the install directory). */\n"
    "  std::string pycache_option;\n"
    "  args_num += bpy_mixar_pycache_python_args(pycache_option, args + args_num);\n",
)
MIXAR_SPDX = " * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited\n"


def _strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def test_the_prefix_is_configured_before_python_starts():
    """The standard library is imported during init, before any startup script."""
    text = (INTERN / "bpy_interface.cc").read_text(encoding="utf-8")
    configure = text.index("bpy_mixar_pycache_config(&config)")
    assert configure < text.index("Py_InitializeFromConfig(&config)")


def test_the_cache_is_per_user_and_shared_with_child_pythons():
    header = HEADER.read_text(encoding="utf-8")
    body = _strip_comments(header)
    assert "BKE_appdir_folder_caches(" in body and '"pycache"' in body
    assert "PyConfig_SetBytesString(config, &config->pycache_prefix" in body
    # Plain `sys.executable` children read the environment ...
    assert "BLI_setenv(BPY_MIXAR_PYCACHE_ENV" in body and '"PYTHONPYCACHEPREFIX"' in body
    # ... and without a usable cache directory nothing is written at all, by
    # this process or by a plain child (which gets no -B of its own).
    empty = body[body.index("if (prefix.empty()) {"):]
    empty = empty[:empty.index("}")]
    assert "config->write_bytecode = 0;" in empty
    assert 'BLI_setenv(BPY_MIXAR_NO_BYTECODE_ENV, "1");' in empty
    assert '"PYTHONDONTWRITEBYTECODE"' in body


def test_isolated_child_pythons_get_the_cache_on_their_command_line():
    """`bpy.app.python_args` carries `-I`, which hides PYTHONPYCACHEPREFIX."""
    body = _strip_comments(HEADER.read_text(encoding="utf-8"))
    assert '"pycache_prefix="' in body and '"-X"' in body and '"-B"' in body
    app = (INTERN / "bpy_app.cc").read_text(encoding="utf-8")
    getter = app[app.index("static PyObject *bpy_app_python_args_get"):]
    getter = getter[:getter.index("\n}\n")]
    assert "const char *args[3];" in getter
    assert "bpy_mixar_pycache_python_args(pycache_option, args + args_num)" in getter


def test_the_header_is_listed_in_the_build():
    cmake = (INTERN / "CMakeLists.txt").read_text(encoding="utf-8")
    assert "  bpy_mixar_pycache.hh\n" in cmake


def _assert_upstream_plus(name, hunks, replacements=()):
    upstream = UPSTREAM_INTERN / name
    if not upstream.exists():
        return  # A linked worktree shares the main checkout's upstream/.
    overlay = (INTERN / name).read_text(encoding="utf-8").replace(MIXAR_SPDX, "")
    for hunk in hunks:
        assert overlay.count(hunk) == 1, hunk
        overlay = overlay.replace(hunk, "")
    for new, old in replacements:
        overlay = overlay.replace(new, old)
    assert overlay == upstream.read_text(encoding="utf-8")


def test_bpy_interface_is_upstream_plus_the_hunk():
    _assert_upstream_plus("bpy_interface.cc", INTERFACE_HUNKS)


def test_bpy_app_is_upstream_plus_the_hunk():
    _assert_upstream_plus("bpy_app.cc", APP_HUNKS, (("const char *args[3];", "const char *args[1];"),))


def test_the_build_ships_no_bytecode():
    """With a prefix set, shipped `.pyc` files are never read: don't make them."""
    build = (ROOT / "scripts/unix/build.sh").read_text(encoding="utf-8")
    assert '"$PYTHON_BIN" -B -m pip install --upgrade --no-user --no-compile --target' in build
    assert 'pip3 install --upgrade --no-compile --target' in build
    assert '"$PYTHON_BIN" -B -c "import truststore"' in build
    assert '"$PYTHON_BIN" -B "$ROOT_DIR/scripts/check_python_runtime.py"' in build
    linux = (ROOT / "scripts/unix/package_linux.sh").read_text(encoding="utf-8")
    assert '"$PYTHON_BIN" -s -B "$ROOT_DIR/scripts/check_python_runtime.py"' in linux
    windows = (ROOT / "scripts/windows/build.bat").read_text(encoding="utf-8")
    runs = [line for line in windows.splitlines() if line.lstrip().startswith('"!PYTHON_BIN!"')]
    assert runs and all(" -B " in line for line in runs), runs
    assert any("pip install" in line and "--no-compile" in line for line in runs)


WINDOWS_SWEEP = ('for /d /r "%PY_BASE%\\%BLENDER_VERSION%" %%D in (__pycache__) '
                 'do if exist "%%D" rmdir /s /q "%%D"')
LINUX_SWEEP = 'find "$STAGING_DIR" -type d -name __pycache__ -prune -exec rm -rf {} +'


def _bytecode_tree(root):
    """A stand-in install: sources, plus `__pycache__` at several depths."""
    for folder in ("python/lib/python3.13/__pycache__", "python/lib/python3.13/json/__pycache__",
                   "scripts/mixar/__pycache__", "scripts/mixar/modules/a/__pycache__/__pycache__"):
        (root / folder).mkdir(parents=True, exist_ok=True)
        (root / folder / "m.cpython-313.pyc").write_bytes(b"pyc")
    (root / "scripts/mixar/mcp.py").write_text("print(1)\n")
    (root / "python/lib/python3.13/json/__init__.py").write_text("\n")


def test_build_outputs_are_swept_of_bytecode():
    """A reused build tree carries `__pycache__` from older runs into the Windows
    install and the Linux tarball, and `-s -B -m ensurepip` (run only when the
    embedded Python lacks pip) still leaves stdlib and pip bytecode, because
    ensurepip runs pip in a child Python without -B and strips PIP_*."""
    windows = (ROOT / "scripts/windows/build.bat").read_text(encoding="utf-8")
    assert windows.count(WINDOWS_SWEEP) == 1
    sweep = windows.index(WINDOWS_SWEEP)
    # After step 8's last Python run, before the build reports success.
    assert windows.index('check_python_runtime.py"') < sweep
    assert '"!PYTHON_BIN!"' not in windows[sweep:]
    assert sweep < windows.index("Successfully installed and verified Python packages")
    linux = (ROOT / "scripts/unix/package_linux.sh").read_text(encoding="utf-8")
    assert linux.count(LINUX_SWEEP) == 1
    assert linux.index('cp -a "$BUILD_ENV_DIR/bin/." "$STAGING_DIR/"') < linux.index(LINUX_SWEEP)
    assert linux.index(LINUX_SWEEP) < linux.index("[7/7] Create archive")


@pytest.mark.skipif(os.name == "nt", reason="the Linux packaging line runs in a POSIX shell")
def test_the_linux_sweep_removes_every_pycache_and_nothing_else(tmp_path):
    staging = tmp_path / "mixar-linux"
    _bytecode_tree(staging)
    subprocess.run(["bash", "-c", "set -euo pipefail; " + LINUX_SWEEP], check=True,
                   env={**os.environ, "STAGING_DIR": str(staging)})
    assert not [p for p in staging.rglob("*") if p.name == "__pycache__" or p.suffix == ".pyc"]
    assert (staging / "scripts/mixar/mcp.py").is_file()
    assert (staging / "python/lib/python3.13/json/__init__.py").is_file()


@pytest.mark.skipif(os.name != "nt", reason="the build.bat line runs in cmd.exe")
def test_the_windows_sweep_removes_every_pycache_and_nothing_else(tmp_path):
    base = tmp_path / "R&D (x) bin"
    _bytecode_tree(base / "5.2")
    script = tmp_path / "sweep.cmd"
    script.write_text("@echo off\nsetlocal EnableDelayedExpansion\n" + WINDOWS_SWEEP + "\n")
    subprocess.run(["cmd.exe", "/d", "/c", str(script)], check=True,
                   env={**os.environ, "PY_BASE": str(base), "BLENDER_VERSION": "5.2"})
    assert not [p for p in base.rglob("*") if p.name == "__pycache__" or p.suffix == ".pyc"]
    assert (base / "5.2/scripts/mixar/mcp.py").is_file()


def test_an_invalid_xdg_cache_home_is_ignored():
    """XDG spec: an empty or relative XDG_CACHE_HOME is invalid and must be ignored.
    Empty made the caches root the per-session temp directory (deleted at exit, so
    every launch recompiled); relative left Python no cache at all."""
    ghost = (ROOT / "src/intern/ghost/intern/GHOST_SystemPathsUnix.cc").read_text(encoding="utf-8")
    caches = ghost[ghost.index("case GHOST_kUserSpecialDirCaches: {"):]
    caches = _strip_comments(caches[:caches.index('return string(home_dir) + "/.cache";')])
    assert 'getenv("XDG_CACHE_HOME")' in caches
    assert "if (cache_dir && cache_dir[0] == '/') {" in caches
    assert "if (cache_dir) {" not in caches


STARTUP_BOOTSTRAP = ROOT / "src/scripts/startup/bootstrap/__init__.py"


def _startup_bootstrap():
    spec = importlib.util.spec_from_file_location("pycache_startup_bootstrap", STARTUP_BOOTSTRAP)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def no_bytecode_env(monkeypatch):
    """Neither variable set; whatever the code under test adds is undone afterwards
    (setenv first, so the undo removes a key that was absent)."""
    for name in ("PYTHONPYCACHEPREFIX", "PYTHONDONTWRITEBYTECODE"):
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)
    return monkeypatch


def _plain_child_import(tmp_path):
    """A plain child (`sys.executable`, `env=dict(os.environ)`) imports a module
    beside its script; returns the source directory."""
    install = tmp_path / "install"
    install.mkdir()
    (install / "helper_mod.py").write_text("VALUE = 1\n")
    (install / "entry.py").write_text("import helper_mod\n")
    subprocess.run([sys.executable, str(install / "entry.py")], check=True, cwd=install,
                   env=dict(os.environ))
    return install


def test_child_pythons_given_a_copy_of_os_environ_share_the_cache(tmp_path, no_bytecode_env):
    """On Windows BLI_setenv (SetEnvironmentVariableW) never reaches the CRT environment
    `os.environ` reads: a child started with `env=dict(os.environ)` wrote 97 .pyc into
    the install. The bootstrap copies the cache into `os.environ`."""
    cache = tmp_path / "pycache"
    no_bytecode_env.setattr(sys, "pycache_prefix", str(cache))
    _startup_bootstrap()._share_bytecode_rule_with_children()
    assert os.environ["PYTHONPYCACHEPREFIX"] == str(cache)
    assert "PYTHONDONTWRITEBYTECODE" not in os.environ
    install = _plain_child_import(tmp_path)
    assert not list(install.rglob("*.pyc"))
    assert list(cache.rglob("helper_mod.*.pyc"))


def test_without_a_cache_child_pythons_write_nothing(tmp_path, no_bytecode_env):
    """No usable cache: never an empty prefix (that would mean "beside the source");
    PYTHONDONTWRITEBYTECODE, as the C side exports it."""
    no_bytecode_env.setattr(sys, "pycache_prefix", None)
    no_bytecode_env.setattr(sys, "dont_write_bytecode", True)
    _startup_bootstrap()._share_bytecode_rule_with_children()
    assert "PYTHONPYCACHEPREFIX" not in os.environ
    assert os.environ["PYTHONDONTWRITEBYTECODE"] == "1"
    assert not list(_plain_child_import(tmp_path).rglob("*.pyc"))


def test_a_writing_interpreter_without_a_cache_exports_nothing(no_bytecode_env):
    no_bytecode_env.setattr(sys, "pycache_prefix", None)
    no_bytecode_env.setattr(sys, "dont_write_bytecode", False)
    _startup_bootstrap()._share_bytecode_rule_with_children()
    assert "PYTHONPYCACHEPREFIX" not in os.environ and "PYTHONDONTWRITEBYTECODE" not in os.environ


def test_the_bytecode_rule_is_shared_before_any_mixar_code_runs():
    """Bootstrap modules (sandbox supervisor, render worker, MCP) start children."""
    text = STARTUP_BOOTSTRAP.read_text(encoding="utf-8")
    register = text[text.index("\ndef register():"):]
    register = register[:register.index("\ndef ", 1)]
    share = register.index("_share_bytecode_rule_with_children()")
    for later in ("_setup_mixar_packages()", "configure_network()", "_load_bootstrap_modules()"):
        assert share < register.index(later), later
