# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""The MCP connector launcher never writes bytecode into the install directory.

It runs the bundle's own Python, so a `__pycache__` written beside the bundled
sources broke the signed macOS app ("Mixar is damaged", issue #2058). The
launcher shares the app's bytecode cache (`sys.pycache_prefix`) or writes none,
and every app start rewrites a launcher left by an older version.
"""

import ast
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from mixar.modules.mcp_bridge.core import installation


def _install(tmp_path):
    """A stand-in install directory: an entry script that imports a sibling module."""
    install = tmp_path / "Mixar.app" / "scripts"
    install.mkdir(parents=True)
    (install / "helper_mod.py").write_text("VALUE = 'imported'\n")
    entry = install / "entry.py"
    entry.write_text("import sys\nsys.path.insert(0, %r)\nimport helper_mod\nprint(helper_mod.VALUE)\n" % str(install))
    return install, entry


def _bytecode_under(path):
    return sorted(p for p in path.rglob("*.pyc"))


@pytest.mark.skipif(os.name == "nt", reason="Unix launcher; the .cmd shares the command line")
def test_the_launcher_writes_bytecode_to_the_app_cache_not_the_install(tmp_path, monkeypatch):
    cache = tmp_path / "Caches" / "Mixar" / "pycache"
    monkeypatch.setattr(installation.sys, "pycache_prefix", str(cache))
    install, entry = _install(tmp_path)
    launcher = installation.provision(sys.executable, entry, sys.executable)
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    assert subprocess.check_output([str(launcher)], text=True, env=env).strip() == "imported"
    assert _bytecode_under(install) == []
    # Python mirrors the source's absolute directory under the prefix.
    cached = cache / str(install).lstrip(os.sep) / ("helper_mod.cpython-%d%d.pyc" % sys.version_info[:2])
    assert cached.is_file()


@pytest.mark.skipif(os.name == "nt", reason="Unix launcher; the .cmd shares the command line")
def test_without_an_app_cache_the_launcher_writes_no_bytecode(tmp_path, monkeypatch):
    monkeypatch.setattr(installation.sys, "pycache_prefix", None)
    install, entry = _install(tmp_path)
    launcher = installation.provision(sys.executable, entry, sys.executable)
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    assert subprocess.check_output([str(launcher)], text=True, env=env).strip() == "imported"
    assert _bytecode_under(tmp_path) == []
    assert " -B " in launcher.read_text()


def test_both_launcher_forms_carry_the_bytecode_arguments():
    """The Windows .cmd and the Unix script are written from one command list."""
    tree = ast.parse(Path(installation.__file__).read_text(encoding="utf-8"))
    provision = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "provision")
    source = ast.unparse(provision)
    assert "command = [str(python), *_bytecode_args(windows), str(script)]" in source
    assert "_cmd_text(command)" in source
    assert "shlex.join(command)" in source


def test_every_app_start_rewrites_an_older_launcher(tmp_path, monkeypatch):
    """runtime._tick provisions on its first tick whether MCP is on or off, so a
    launcher written by an older Mixar (no bytecode flag) is replaced at once."""
    from mixar.modules.mcp_bridge.core import runtime, tool_snapshot
    from mixar.modules.common.ui_control.core import service

    cache = tmp_path / "pycache"
    monkeypatch.setattr(installation.sys, "pycache_prefix", str(cache))
    old = installation.directory() / "mixar-mcp"
    old.parent.mkdir(parents=True)
    old.write_text("#!/bin/sh\nexec /old/python3.13 /old/mcp.py \"$@\"\n")

    wm = SimpleNamespace(mixie_instance_id="fixture", mixie_chat_is_logged_in=False,
                         mixie_chat_session_expired=False)
    monkeypatch.setattr(runtime, "bpy", SimpleNamespace(
        context=SimpleNamespace(window_manager=wm, scene=SimpleNamespace(name="Scene", mixie_session_id="")),
        app=SimpleNamespace(binary_path=str(tmp_path / "Mixar.app/Contents/MacOS/Mixar")),
        utils=SimpleNamespace(resource_path=lambda kind: str(tmp_path / "Mixar.app/Contents/Resources/5.2"))))
    monkeypatch.setattr(runtime, "get_config", lambda: {"mcp_enabled": False})
    monkeypatch.setattr(runtime, "get_server_url", lambda: "http://127.0.0.1:1")
    monkeypatch.setattr(runtime, "_registered", True)
    monkeypatch.setattr(runtime, "_provisioned", None)  # A fresh app process.
    monkeypatch.setattr(runtime, "_server", None)
    for module, name, value in (
            ("mixar.modules.space_mixie_chat.core.connection_manager", "get_connection_manager",
             lambda: SimpleNamespace(is_connected=False)),
            ("mixar.modules.space_mixie_chat.core.session", "get_session_manager",
             lambda: SimpleNamespace(instance_id="fixture"))):
        monkeypatch.setitem(sys.modules, module, SimpleNamespace(**{name: value}))
    monkeypatch.setattr(service, "unregister", lambda *a, **kw: None)
    monkeypatch.setattr(tool_snapshot, "forget", lambda: None)

    assert runtime._tick() == 1.0
    launcher = installation.directory() / ("mixar-mcp.cmd" if os.name == "nt" else "mixar-mcp")
    text = launcher.read_text()
    option = "pycache_prefix=" + str(cache)
    # The .cmd quotes it (and names a cache under %LOCALAPPDATA% by that variable).
    assert (installation._cmd_argument(option) if os.name == "nt" else option) in text
    assert "/old/" not in text
    assert runtime._provisioned is False


# --- The Windows .cmd launcher ---------------------------------------------------
# cmd.exe cannot run here, so these tests read the .cmd text through a model of the
# documented rules: batch percent expansion, cmd's quote/`^`/`&` handling, then the
# program's own argv parser (CommandLineToArgvW). The Windows-only test at the end
# runs the real thing.

PYTHON_EXE = r"C:\Program Files\Mixar\5.2\python\bin\python.exe"
MCP_SCRIPT = r"C:\Program Files\Mixar\5.2\scripts\mixar\mcp.py"


def _expand_percent(line, env, args=""):
    """Batch-file phase 1: `%%` is `%`, `%*` the caller's arguments, `%NAME%` its
    value (case-insensitive; empty when undefined), a lone `%` dropped."""
    out, i = [], 0
    while i < len(line):
        if line[i] != "%":
            out.append(line[i])
            i += 1
        elif line.startswith("%%", i):
            out.append("%")
            i += 2
        elif line.startswith("%*", i):
            out.append(args)
            i += 2
        else:
            end = line.find("%", i + 1)
            if end < 0:
                i += 1
                continue
            out.append({k.upper(): v for k, v in env.items()}.get(line[i + 1:end].upper(), ""))
            i = end + 1
    return "".join(out)


def _split_commands(line):
    """cmd.exe phase 2: `"` toggles quoting; outside quotes `^` escapes the next
    character and `&`, `|`, `<`, `>` end the command (or redirect it)."""
    commands, current, quoted, i = [], [], False, 0
    while i < len(line):
        c = line[i]
        if c == '"':
            quoted = not quoted
            current.append(c)
        elif not quoted and c == "^" and i + 1 < len(line):
            i += 1
            current.append(line[i])
        elif not quoted and c in "&|<>":
            commands.append("".join(current))
            current = []
        else:
            current.append(c)
        i += 1
    commands.append("".join(current))
    return [command for command in commands if command.strip()]


def _argv(line):
    """The program's argv (CommandLineToArgvW): 2n backslashes before `"` are n and
    a delimiter, 2n+1 are n and a literal `"`; other backslashes are literal."""
    args, current, started, quoted, i = [], [], False, False, 0
    while i < len(line):
        c = line[i]
        if c == "\\":
            n = len(line[i:]) - len(line[i:].lstrip("\\"))
            i += n
            if i < len(line) and line[i] == '"':
                current.append("\\" * (n // 2))
                if n % 2:
                    current.append('"')
                    i += 1
            else:
                current.append("\\" * n)
            started = True
            continue
        if c == '"':
            quoted, started = not quoted, True
        elif c in " \t" and not quoted:
            if started:
                args.append("".join(current))
                current, started = [], False
        else:
            current.append(c)
            started = True
        i += 1
    if started:
        args.append("".join(current))
    return args


def _run_cmd(text, env=None, code_page=None):
    """The argv of each program the launcher starts, in order. Runs `@echo off`,
    `if not defined NAME goto LABEL`, `exit /b`, `:LABEL` and command lines; an
    empty variable is undefined in cmd.exe. `code_page`: cmd.exe decodes the UTF-8
    file in the console code page."""
    assert text.endswith("\r\n") and "\n" not in text.replace("\r\n", ""), repr(text)
    if code_page:
        text = text.encode("utf-8").decode(code_page)
    env = {k.upper(): v for k, v in (env or {}).items() if v}
    lines = text.split("\r\n")[:-1]
    assert lines[0] == "@echo off", text
    started, i = [], 1
    while i < len(lines):
        line, words = lines[i], lines[i].split()
        i += 1
        if not words or line.startswith(":"):
            continue
        if words[:3] == ["if", "not", "defined"]:
            assert len(words) == 6 and words[4] == "goto", line
            if words[3].upper() not in env:
                i = lines.index(":" + words[5]) + 1
            continue
        if line == "exit /b":
            break
        started += [_argv(command) for command in _split_commands(_expand_percent(line, env))]
    return started


def _single_line(command):
    """A launcher with no %LOCALAPPDATA% guard: `@echo off` and one command line."""
    text = installation._cmd_text(command)
    assert text.count("\r\n") == 2 and "goto" not in text, text
    return text


def test_the_model_reproduces_the_unquoted_ampersand_failure():
    """`subprocess.list2cmdline` quotes only arguments with spaces: cmd.exe split
    `C:\\Users\\R&D\\...` into two commands and the launcher failed."""
    prefix = r"pycache_prefix=C:\Users\R&D\AppData\Local\Mixar\Mixar\Cache\pycache"
    old = "@echo off\r\n" + subprocess.list2cmdline([PYTHON_EXE, "-X", prefix, MCP_SCRIPT]) + " %*\r\n"
    assert len(_run_cmd(old)) == 2


@pytest.mark.parametrize("folder", [
    r"C:\Users\R&D", r"C:\Users\a^b", r"C:\Users\x|y", r"C:\Users\Q (A) & <B>",
    r"C:\Users\100% sure", r"C:\Users\%PATH%", r"C:\Users\%%x%%", r"D:\no spaces"])
def test_every_argument_is_quoted_so_cmd_metacharacters_stay_literal(folder, monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    command = [folder + r"\python.exe", "-X", "pycache_prefix=" + folder + r"\cache", folder + r"\mcp.py"]
    text = _single_line(command)
    assert text.endswith(" %*\r\n")
    assert _run_cmd(text, env={"PATH": "EXPANDED"}) == [command]


def test_a_trailing_backslash_does_not_escape_the_closing_quote(monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    command = [PYTHON_EXE, "-X", "pycache_prefix=D:\\cache\\", MCP_SCRIPT]
    assert '"pycache_prefix=D:\\cache\\\\"' in _single_line(command)
    assert _run_cmd(installation._cmd_text(command)) == [command]


def test_options_are_quoted_too():
    text = _single_line([PYTHON_EXE, "-B", MCP_SCRIPT])
    assert text == '@echo off\r\n"%s" "-B" "%s" %%*\r\n' % (PYTHON_EXE, MCP_SCRIPT)


LOCAL = "C:\\Users\\J\u00f6hn & Co\\AppData\\Local"
CACHE = LOCAL + "\\Mixar\\Mixar\\Cache\\pycache"


def test_a_cache_under_localappdata_is_written_as_the_variable(monkeypatch):
    """cmd.exe decodes the UTF-8 .cmd in the console code page (437 on the QA box): a
    literal `Jöhn` reached Python mangled and the launcher silently never cached."""
    monkeypatch.setenv("LOCALAPPDATA", LOCAL)
    command = [PYTHON_EXE, "-X", "pycache_prefix=" + CACHE, MCP_SCRIPT]
    text = installation._cmd_text(command)
    assert '"pycache_prefix=%LOCALAPPDATA%\\Mixar\\Mixar\\Cache\\pycache"' in text
    assert text.isascii() and "chcp" not in text
    for code_page in (None, "cp437", "cp850", "cp1252"):
        assert _run_cmd(text, env={"LOCALAPPDATA": LOCAL}, code_page=code_page) == [command]
    # Written literally, the same path does not survive the code page.
    literal = "@echo off\r\n" + " ".join('"%s"' % arg for arg in command) + " %*\r\n"
    assert _run_cmd(literal, env={"LOCALAPPDATA": LOCAL}, code_page="cp437") != [command]


def test_without_localappdata_the_launcher_writes_no_bytecode(monkeypatch):
    """A client that starts the launcher without LOCALAPPDATA would expand it to
    nothing: the cache would be `\\Mixar\\...` at the root of the current drive. That
    start runs with -B instead; `goto`, not a parenthesised block, so a `)` in a
    path or an argument cannot end it."""
    monkeypatch.setenv("LOCALAPPDATA", LOCAL)
    python, script = r"C:\Mixar (beta)\python.exe", r"C:\Mixar (beta)\mcp.py"
    command = [python, "-X", "pycache_prefix=" + CACHE, script]
    text = installation._cmd_text(command)
    assert text.split("\r\n") == [
        "@echo off",
        "if not defined LOCALAPPDATA goto nocache",
        '"%s" "-X" "pycache_prefix=%%LOCALAPPDATA%%\\Mixar\\Mixar\\Cache\\pycache" "%s" %%*' % (python, script),
        "exit /b",
        ":nocache",
        '"%s" "-B" "%s" %%*' % (python, script),
        ""]
    for code_page in (None, "cp437"):
        assert _run_cmd(text, env={"LOCALAPPDATA": LOCAL}, code_page=code_page) == [command]
        for env in ({}, {"LOCALAPPDATA": ""}, {"PATH": "C:\\Windows"}):
            assert _run_cmd(text, env=env, code_page=code_page) == [[python, "-B", script]]


@pytest.mark.parametrize("prefix", [None, "D:\\cache\\pycache", "C:\\Users\\Ann\\AppData\\Local\\pycache"])
def test_a_literal_cache_or_no_cache_keeps_the_single_line(prefix, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", LOCAL)
    monkeypatch.setattr(installation.sys, "pycache_prefix", prefix)
    command = [PYTHON_EXE, *installation._bytecode_args(True), MCP_SCRIPT]
    assert _run_cmd(_single_line(command)) == [command]


def test_localappdata_matches_like_windows_paths(monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", LOCAL.upper() + "\\")
    assert installation._localappdata_rest(CACHE) == "\\Mixar\\Mixar\\Cache\\pycache"
    assert installation._localappdata_rest(LOCAL.replace("\\", "/") + "/pycache") == "/pycache"
    assert installation._localappdata_rest(LOCAL + "Low\\Mixar\\pycache") is None  # a sibling
    assert installation._localappdata_rest(LOCAL) is None
    assert installation._localappdata_rest("D:\\elsewhere\\pycache") is None
    monkeypatch.delenv("LOCALAPPDATA")
    assert installation._localappdata_rest(CACHE) is None


def test_percent_inside_localappdata_rest_is_escaped(monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", LOCAL)
    command = [PYTHON_EXE, "-X", "pycache_prefix=" + LOCAL + "\\100%\\pycache", MCP_SCRIPT]
    text = installation._cmd_text(command)
    assert "%LOCALAPPDATA%\\100%%\\pycache" in text
    assert _run_cmd(text, env={"LOCALAPPDATA": LOCAL}) == [command]
    assert _run_cmd(text) == [[PYTHON_EXE, "-B", MCP_SCRIPT]]


@pytest.mark.parametrize("prefix, local, windows, expected", [
    (CACHE, LOCAL, True, ["-X", "pycache_prefix=" + CACHE]),  # written as %LOCALAPPDATA%
    ("D:\\cache\\pycache", LOCAL, True, ["-X", "pycache_prefix=D:\\cache\\pycache"]),
    ("D:\\J\u00f6hn\\pycache", LOCAL, True, ["-B"]),  # would reach Python mangled
    (LOCAL + "\\J\u00f6hn\\pycache", "C:\\Users\\Ann\\AppData\\Local", True, ["-B"]),
    ("/Users/J\u00f6hn/Library/Caches/Mixar/pycache", None, False,
     ["-X", "pycache_prefix=/Users/J\u00f6hn/Library/Caches/Mixar/pycache"]),  # sh reads UTF-8
    (None, LOCAL, True, ["-B"]),
])
def test_bytecode_arguments_per_platform(prefix, local, windows, expected, monkeypatch):
    monkeypatch.setattr(installation.sys, "pycache_prefix", prefix)
    if local:
        monkeypatch.setenv("LOCALAPPDATA", local)
    else:
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert installation._bytecode_args(windows) == expected


@pytest.mark.skipif(os.name != "nt", reason="runs the .cmd in cmd.exe")
@pytest.mark.parametrize("with_localappdata", [True, False])
@pytest.mark.parametrize("style", ["cmd_c", "direct", "node_s"])
def test_the_cmd_launcher_runs_with_tricky_paths(style, with_localappdata, tmp_path, monkeypatch):
    """The real cmd.exe, three ways an MCP client starts the launcher, with `&`, `^`,
    `%`, parentheses and a non-ASCII user name in every path; with LOCALAPPDATA the
    cache is used, without it the launcher runs with -B and writes nothing anywhere."""
    local = tmp_path / "J\u00f6hn & R^D (1) 100%" / "AppData" / "Local"
    cache = local / "Mixar" / "Mixar" / "Cache" / "pycache"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setattr(installation.sys, "pycache_prefix", str(cache))
    install, entry = _install(tmp_path / "Pr&gram (x86) 50%")
    entry.write_text(entry.read_text().replace(
        "print(helper_mod.VALUE)",
        "print(helper_mod.VALUE, sys.flags.dont_write_bytecode, ascii(sys.pycache_prefix))"))
    launcher = installation.provision(sys.executable, entry, sys.executable)
    assert "if not defined LOCALAPPDATA goto nocache" in launcher.read_text()
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PYTHON")}
    if not with_localappdata:
        env.pop("LOCALAPPDATA")
    if style == "cmd_c":
        argv = ["cmd.exe", "/d", "/c", str(launcher)]
    elif style == "direct":
        argv = [str(launcher)]
    else:
        argv = 'cmd.exe /d /s /c ""%s""' % launcher
    # Where an unguarded `%LOCALAPPDATA%\Mixar\...` lands when the variable is missing.
    junk = Path(tmp_path.anchor, "Mixar", "Mixar", "Cache", "pycache")
    existed = junk.exists()
    out = subprocess.check_output(argv, text=True, env=env, cwd=tmp_path).strip()
    assert _bytecode_under(install) == []
    if with_localappdata:
        assert out == "imported 0 " + ascii(str(cache))
        assert list(cache.rglob("helper_mod.*.pyc"))
    else:
        assert out == "imported 1 None"
        assert not cache.exists()
        assert junk.exists() == existed and not (existed and list(junk.rglob("helper_mod.*.pyc")))
