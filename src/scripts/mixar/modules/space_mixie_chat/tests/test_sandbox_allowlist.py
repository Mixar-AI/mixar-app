# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent-script sandbox allowlist — builtins and injected modules.

Agent scripts run against a curated ``__builtins__`` plus a fixed set of
pre-injected modules; there is no real ``__import__``. Scripts that could not
write ``try/except`` or ``type(x)`` burned a whole model round trip on
"name 'type' is not defined" / "name 'ImportError' is not defined", so those
names are part of the contract now. The exclusions below are the security
half of the same contract and must not drift.
"""

import os
import sys
from unittest.mock import MagicMock

import pytest

_SRC_SCRIPTS = os.path.abspath(
    os.path.join(os.path.dirname(__file__), *([".."] * 4))
)
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)

# Blender-only modules the executor imports inside execute(); stubbing them
# lets the real sandbox run outside Blender.
for _dep in (
    "keyring", "websocket", "requests", "jwt", "sentry_sdk",
    "bmesh", "mathutils", "bpy_extras", "imbuf",
):
    sys.modules.setdefault(_dep, MagicMock(name=_dep))

from mixar.modules.space_mixie_chat.core.sandbox_builtins import (  # noqa: E402
    SAFE_BUILTIN_NAMES,
    get_safe_builtins,
)
from mixar.modules.space_mixie_chat.core.sandbox_validator import (  # noqa: E402
    _BLOCKED_DUNDER_ATTRS,
    validate_script_ast,
)

# Names a script must be able to use.
REQUIRED = (
    "type",
    "Exception", "ValueError", "KeyError", "TypeError", "IndexError",
    "AttributeError", "RuntimeError", "ImportError", "ZeroDivisionError",
    "StopIteration",
)

# Names that must never be reachable: they either create code
# (eval/exec/compile/__build_class__), import freely (__import__), read a raw
# __dict__ past the dunder guard (vars/globals/locals), or block on stdin.
FORBIDDEN = (
    "super", "__build_class__", "input", "breakpoint", "vars", "eval",
    "exec", "compile", "__import__", "locals",
)


@pytest.mark.parametrize("name", REQUIRED)
def test_required_name_is_exposed(name):
    assert name in SAFE_BUILTIN_NAMES
    assert name in get_safe_builtins()


@pytest.mark.parametrize("name", FORBIDDEN)
def test_forbidden_name_is_absent(name):
    assert name not in SAFE_BUILTIN_NAMES
    assert name not in get_safe_builtins()


def test_exception_classes_are_the_real_ones():
    """A caught ValueError must be builtins.ValueError, not a look-alike."""
    import builtins

    safe = get_safe_builtins()
    for name in REQUIRED:
        assert safe[name] is getattr(builtins, name)


def test_type_cannot_be_used_to_declare_a_class():
    """`type` is exposed but `class` statements stay impossible."""
    assert "__build_class__" not in get_safe_builtins()
    ns = {"__builtins__": get_safe_builtins()}
    with pytest.raises(NameError):
        exec("class Foo:\n    pass\n", ns)  # noqa: S102


def test_type_result_still_hits_the_dunder_guard():
    """type(x) hands back a class, but every escape attr stays blocked."""
    safe = get_safe_builtins()
    cls = safe["type"](())
    for attr in ("__subclasses__", "__bases__", "__mro__", "__dict__"):
        with pytest.raises(AttributeError):
            safe["getattr"](cls, attr)
        assert safe["hasattr"](cls, attr) is False
        assert validate_script_ast(f"type(()).{attr}") is not None


def test_try_except_script_validates_and_runs():
    ns = {"__builtins__": get_safe_builtins()}
    script = (
        "out = []\n"
        "try:\n"
        "    raise ValueError('boom')\n"
        "except (ValueError, KeyError) as exc:\n"
        "    out.append(type(exc).__name__ if False else 'ValueError')\n"
        "except ImportError:\n"
        "    out.append('import')\n"
    )
    assert validate_script_ast(script) is None
    exec(script, ns)  # noqa: S102
    assert ns["out"] == ["ValueError"]


# --- injected modules (executor.exec_namespace + _restricted_import) ---------

# Pure-Python stdlib: no process, file or network access. `_allowed` is derived
# from the namespace keys, so injecting one is all it takes for `import x`.
INJECTED = (
    "itertools", "functools", "statistics", "heapq", "bisect", "copy",
    "textwrap", "fractions", "decimal",
)

# Modules that must NOT be in the namespace even though they are pure Python:
# each one resolves an attribute (or a module) from a caller-supplied string,
# which walks straight past the wrapped getattr.
WITHDRAWN = ("runpy", "operator")


@pytest.fixture(scope="module")
def script_executor():
    from mixar.modules.space_mixie_chat.core import executor

    return executor.ScriptExecutor()


@pytest.mark.parametrize("name", INJECTED)
def test_injected_module_can_be_imported(script_executor, name):
    result = script_executor.execute(
        f"import {name}\nprint({name}.__name__)\n", push_undo=False
    )
    assert result.success, result.error
    assert name in result.output


def test_injected_module_is_usable(script_executor):
    result = script_executor.execute(
        "import itertools, statistics\n"
        "print(list(itertools.islice(itertools.count(), 3)),"
        " statistics.mean([1, 2, 3]))\n",
        push_undo=False,
    )
    assert result.success, result.error
    assert "[0, 1, 2] 2" in result.output


def test_unknown_module_is_refused_with_the_allowed_list(script_executor):
    result = script_executor.execute("import scipy\n", push_undo=False)
    assert not result.success
    assert "Module 'scipy' is not available" in result.error
    assert "Allowed modules:" in result.error
    for name in INJECTED:
        assert name in result.error


def test_os_and_pathlib_stay_refused(script_executor):
    for name in ("os", "pathlib", "subprocess", "shutil", "socket"):
        result = script_executor.execute(f"import {name}\n", push_undo=False)
        assert not result.success, name


def test_type_and_exceptions_work_in_a_real_script(script_executor):
    result = script_executor.execute(
        "try:\n"
        "    raise ImportError('nope')\n"
        "except ImportError as exc:\n"
        "    print(type(exc).__name__, type(3) is int)\n",
        push_undo=False,
    )
    assert result.success, result.error
    assert "ImportError True" in result.output


@pytest.mark.parametrize("name", WITHDRAWN)
def test_withdrawn_module_is_refused(script_executor, name):
    """runpy.run_module("os") and operator.attrgetter are sandbox escapes."""
    result = script_executor.execute(f"import {name}\n", push_undo=False)
    assert not result.success
    assert f"Module '{name}' is not available" in result.error
    assert "Allowed modules:" in result.error
    assert name not in result.error.split("Allowed modules:")[1]


def test_runpy_is_unreachable_without_an_import(script_executor):
    result = script_executor.execute("print(runpy.run_module('os'))\n", push_undo=False)
    assert not result.success
    assert "runpy" in result.error


# --- escape probes: each one succeeded before this guard existed -------------


def test_raw_getattribute_chain_fails_at_the_first_step(script_executor):
    """object.__getattribute__(cls, '__subclasses__') was the live bypass.

    `object` is an allowed builtin and __getattribute__ is the raw C slot, so
    the chain ().__getattribute__('__class__') -> __subclasses__ -> __globals__
    reached 234 classes and a real module namespace. It must now die on the
    FIRST hop, in both the AST pass and at runtime.
    """
    chain = "print(().__getattribute__('__class__'))\n"
    assert validate_script_ast(chain) is not None
    result = script_executor.execute(chain, push_undo=False)
    assert not result.success
    assert "__getattribute__" in result.error

    safe = get_safe_builtins()
    with pytest.raises(AttributeError):
        safe["getattr"]((), "__getattribute__")
    assert safe["hasattr"]((), "__getattribute__") is False


@pytest.mark.parametrize(
    "attr",
    ["__getattribute__", "__setattr__", "__delattr__", "__reduce__",
     "__reduce_ex__", "__subclasshook__", "__getattr__"],
)
def test_raw_slot_is_blocked_by_both_layers(attr):
    assert attr in _BLOCKED_DUNDER_ATTRS
    assert validate_script_ast(f"().{attr}") is not None
    safe = get_safe_builtins()
    with pytest.raises(AttributeError):
        safe["getattr"]((), attr)


def test_format_string_cannot_reach_a_blocked_dunder(script_executor):
    """'{0.__class__}'.format(x) does the attribute walk in C -- no Attribute
    node, no wrapped getattr. The literal itself is the violation."""
    for script in (
        "print('{0.__class__}'.format(()))\n",
        "print('{x.__class__}'.format_map({'x': ()}))\n",
        "spec = '{0.__init__.__globals__}'\nprint(spec.format(print))\n",
    ):
        assert validate_script_ast(script) is not None, script
        assert not script_executor.execute(script, push_undo=False).success

    # f-strings already produce a real Attribute node
    assert validate_script_ast("x = ()\nprint(f'{x.__class__}')\n") is not None


def test_format_string_without_a_dunder_still_works(script_executor):
    result = script_executor.execute(
        "print('{0}-{1.real}'.format('a', 2))\n", push_undo=False
    )
    assert result.success, result.error
    assert "a-2" in result.output


def test_string_module_is_proxied_without_formatter(script_executor):
    """string.Formatter().get_field() returns the OBJECT, not a rendered repr,
    so it bypasses the dunder guard entirely; the proxy drops it."""
    ok = script_executor.execute(
        "import string\nprint(string.digits, string.Template('$a').substitute(a='z'))\n",
        push_undo=False,
    )
    assert ok.success, ok.error
    assert "0123456789 z" in ok.output

    bad = script_executor.execute(
        "import string\nprint(string.Formatter())\n", push_undo=False
    )
    assert not bad.success
    assert "string.Formatter is not available" in bad.error


def test_functools_cannot_hand_out_the_real_getattr(script_executor):
    """functools.partial only ever binds the wrapped getattr -- the script has
    no other one -- so the guard still fires through the partial."""
    result = script_executor.execute(
        "import functools\n"
        "f = functools.partial(getattr, ())\n"
        "try:\n"
        "    f('__class__')\n"
        "    print('LEAKED')\n"
        "except AttributeError as exc:\n"
        "    print('blocked:', exc)\n",
        push_undo=False,
    )
    assert result.success, result.error
    assert "LEAKED" not in result.output
    assert "blocked:" in result.output


def test_copy_returns_no_new_handles(script_executor):
    """copy/deepcopy return same-type values; modules and classes are not
    copyable, so there is no path to an object the script did not already hold."""
    result = script_executor.execute(
        "import copy\n"
        "print(copy.deepcopy({'a': [1, 2]}), copy.copy((1, 2)))\n",
        push_undo=False,
    )
    assert result.success, result.error
    assert "{'a': [1, 2]} (1, 2)" in result.output
