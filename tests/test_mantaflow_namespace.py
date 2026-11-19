# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run the actual native namespace constructor under restricted Python builtins.

No Blender build is needed: the extracted constructor only uses public CPython
APIs. PyDLL keeps the GIL and the caller's Python frame, which mirrors fluid
evaluation only when the modifier evaluates on the main thread inside a script;
a TBB worker has no Python frame and already got the interpreter builtins.
"""
import builtins
import ctypes
import functools
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
REL = Path('intern/mantaflow/intern/MANTA_main.cpp')
UPSTREAM_ROOTS = (
    *([Path(os.environ['MIXAR_UPSTREAM_DIR'])] if os.environ.get('MIXAR_UPSTREAM_DIR') else []),
    ROOT / 'upstream',
    ROOT.parents[1] / 'upstream',  # .worktrees/<name> inside the main checkout
)
UPSTREAM = next((r / REL for r in UPSTREAM_ROOTS if (r / REL).exists()), None)
MIXAR_SPDX = ' * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited\n'
FENCE = re.compile(r'[ \t]*/\* MIXAR-2066 begin \*/\n.*?[ \t]*/\* MIXAR-2066 end \*/\n', re.S)
UPSTREAM_LINE = '  PyObject *builtins = PyEval_GetBuiltins();\n'
FIXED_CALL = 'PyModule_GetDict(PyImport_AddModule("builtins"))'
HEADER = '''extern "C" {
struct _object;
typedef _object PyObject;
PyObject *PyEval_GetBuiltins();
PyObject *PyImport_AddModule(const char *);
PyObject *PyModule_GetDict(PyObject *);
PyObject *PyModule_New(const char *);
int PyModule_AddStringConstant(PyObject *, const char *, const char *);
int PyModule_AddObject(PyObject *, const char *, PyObject *);
int PyModule_AddObjectRef(PyObject *, const char *, PyObject *);
PyObject *PyUnicode_InternFromString(const char *);
}
'''


def constructor(source):
    start = source.index('static PyObject *manta_python_main_module_create(')
    return source[start:source.index('\n}\n', start) + 3]


def build(source, library):
    command = ['c++', '-shared', '-fPIC', str(source), '-o', str(library)]
    if sys.platform == 'darwin':
        command[1:1] = ['-undefined', 'dynamic_lookup']
    subprocess.run(command, check=True, capture_output=True, text=True)


@functools.cache
def compiler_works():
    """True when c++ builds a trivial shared library (not e.g. the macOS stub without CLT)."""
    with tempfile.TemporaryDirectory() as folder:
        source = Path(folder) / 'trivial.cpp'
        source.write_text('extern "C" int trivial() { return 0; }\n')
        try:
            build(source, Path(folder) / 'trivial.so')
        except (OSError, subprocess.CalledProcessError):
            return False
    return True


def compile_create(cpp_file, folder):
    """Compile the file's constructor into a probe library; return its entry point."""
    if sys.platform == 'win32' or not shutil.which('c++'):
        pytest.skip('standalone CPython native probe needs macOS or Linux and c++')
    if not compiler_works():
        pytest.skip('c++ cannot build a shared library here')
    source, library = folder / 'probe.cpp', folder / 'probe.so'
    # Public ABI declarations avoid requiring a full Python development package.
    source.write_text(HEADER + constructor(cpp_file.read_text()) + '''
extern "C" PyObject *create_namespace() {
  return manta_python_main_module_create("<manta_namespace>");
}
''')
    try:
        build(source, library)
    except subprocess.CalledProcessError as error:
        pytest.fail(f'compiling the constructor from {cpp_file} failed:\n{error.stderr}')
    dll = ctypes.PyDLL(str(library))
    dll.create_namespace.restype = ctypes.py_object
    dll.create_namespace.argtypes = []
    return dll.create_namespace


def refuse_import(*args, **kwargs):
    raise ImportError('sandbox import refused')


@pytest.fixture(scope='module')
def native_create(tmp_path_factory):
    return compile_create(ROOT / 'src' / REL, tmp_path_factory.mktemp('manta_overlay'))


@pytest.mark.parametrize('restricted', [False, True])
def test_native_namespace_does_not_inherit_callers_builtins(native_create, restricted):
    caller_builtins = {'__import__': refuse_import} if restricted else vars(builtins)
    scope = {'__builtins__': caller_builtins, 'create': native_create}
    exec('module = create()', scope)
    module = scope['module']
    assert module.__builtins__ is vars(builtins)
    exec('import math\nvalue = math.sqrt(9)\nnames = globals()', vars(module))
    assert module.value == 3
    assert module.names is vars(module)


def test_probe_detects_upstream_constructor_inheriting_restricted_builtins(tmp_path):
    """Pin that the probe above would fail on upstream's PyEval_GetBuiltins()."""
    if UPSTREAM is None:
        pytest.skip('upstream Blender source not found (set MIXAR_UPSTREAM_DIR)')
    caller_builtins = {'__import__': refuse_import}
    scope = {'__builtins__': caller_builtins, 'create': compile_create(UPSTREAM, tmp_path)}
    exec('module = create()', scope)
    assert scope['module'].__builtins__ is not vars(builtins)
    assert scope['module'].__builtins__ is caller_builtins


def test_overlay_is_upstream_plus_the_fenced_hunk():
    if UPSTREAM is None:
        pytest.skip('upstream Blender source not found (set MIXAR_UPSTREAM_DIR)')
    upstream = UPSTREAM.read_text()
    overlay = (ROOT / 'src' / REL).read_text()
    hunks = FENCE.findall(overlay)
    assert len(hunks) == 1, 'expected exactly one MIXAR-2066 fenced block'
    assert FIXED_CALL in hunks[0] and 'PyEval_GetBuiltins' not in hunks[0]
    marker = '@@MIXAR-2066@@\n'
    unpatched = FENCE.sub(marker, overlay.replace(MIXAR_SPDX, '', 1))
    if upstream.count(UPSTREAM_LINE) != 1 or unpatched != upstream.replace(UPSTREAM_LINE, marker):
        pytest.fail(
            'upstream changed manta_python_main_module_create (or MANTA_main.cpp), or an overlay '
            'edit is not fenced: re-copy upstream and re-apply the MIXAR-2066 hunk, or drop the '
            'overlay if upstream fixed it',
            pytrace=False,
        )
