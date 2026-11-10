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

import re
from pathlib import Path

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
    # ... and without a usable cache directory nothing is written at all.
    assert "config->write_bytecode = 0;" in body


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
