# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unreal Engine on this machine, for the engine chip's Connect Unreal
(``engine_connect.connect(engine="unreal")``).

- ``find_unreal()``: an installed Unreal Engine 5.8+ (the Epic Games
  Launcher's installs; ``MIXAR_UNREAL`` overrides). Unreal is never
  downloaded: the Launcher owns its installs.
- ``create_project(folder, name, unreal)``: a new third-person game from the
  engine's own template (``TP_ThirdPersonBP`` plus its shared Characters,
  LevelPrototyping and Input content).
- ``install_plugin(uproject, mode)``: Mixar Link for Unreal ``PLUGIN_VERSION``
  (``PLUGIN_URL``, refused unless it matches ``PLUGIN_SHA256``) unpacked into ``<project>/Plugins/MixarLink``, the plugins
  it needs enabled in the ``.uproject``, Unreal's MCP server turned on
  (``MCP_PORT``) and the editor's background throttle off (Mixar drives the
  editor while Mixar has the focus; a throttled editor takes seconds per
  frame) in ``Config/DefaultEditorPerProjectUserSettings.ini``, that port
  pinned to the loopback address in ``Config/DefaultEngine.ini`` (Unreal's
  HTTP server binds ``localhost`` by default, but a project may set
  ``DefaultBindAddress=any`` for every port), and the
  project mode in ``Config/DefaultMixarLink.ini``: ``owned`` for a game Mixar
  made (Mixar edits any level and sets the main level), ``plugin`` for the
  user's own project (Mixar edits only levels under ``/Game/Mixar``).
- ``open_unreal(unreal, uproject)``: the editor on the project.

The editor then writes its discovery file (``engine_link``). Nothing here
leaves the machine except the plugin download.
"""

from __future__ import annotations

import glob
import hashlib
import io
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

# Mixar Link for Unreal: one exact release, checked before it is installed.
# A new release is these two lines (sha256 of the release's MixarLink.zip).
PLUGIN_VERSION = "0.5.2"
PLUGIN_SHA256 = "f8a7d58f4a456ea45ceaf759a9ab9a2f159b235591565927c259d36115e918d0"
PLUGIN_REPO = "Mixar-AI/mixar-engine-unreal"
PLUGIN_URL = f"https://github.com/{PLUGIN_REPO}/releases/download/v{PLUGIN_VERSION}/MixarLink.zip"
CHECKSUM_FAILED = ("The downloaded Mixar Link for Unreal is not the release Mixar expects (checksum mismatch); "
                   "nothing was installed. Try again, or update Mixar.")
UNREAL_MIN = (5, 8)
MCP_PORT = 9880
MCP_SECTION = "[/Script/ModelContextProtocolEngine.ModelContextProtocolSettings]"
PERFORMANCE_SECTION = "[/Script/UnrealEd.EditorPerformanceSettings]"
LISTENERS_SECTION = "[HTTPServer.Listeners]"
# Per-port override: wins over a project-wide DefaultBindAddress.
LISTENER_OVERRIDE = f"+ListenerOverrides=(Port={MCP_PORT},BindAddress=localhost)"
MODE_SECTION = "[MixarLink]"
MODES = ("owned", "plugin")
# Unreal's MCP server and the toolsets Mixar Link sits beside; Python runs the
# plugin; Editor Scripting is what its tools call.
REQUIRED_PLUGINS = ("ModelContextProtocol", "AllToolsets", "PythonScriptPlugin", "EditorScriptingUtilities",
                    "MixarLink")
TEMPLATE = "TP_ThirdPersonBP"
TEMPLATE_PACKS = ("Characters", "LevelPrototyping", "Input")
# What Connect Unreal changes in the user's project, for the Connect dialog.
PROJECT_CHANGES = (
    "Mixar Link (open source) is installed into the project's Plugins folder.",
    "It enables the Model Context Protocol, All Toolsets, Python Script and",
    "Editor Scripting plugins, and turns on Unreal's MCP server at editor start",
    f"(this computer only, port {MCP_PORT}; any program on this computer can use it",
    "while the editor runs). The editor keeps full speed in the background.",
    "Close the project in Unreal first.",
)
NOT_INSTALLED = ("Unreal Engine 5.8 or newer is not installed. Install it from the Epic Games Launcher "
                 "(Unreal Engine > Library > Engine Versions), then connect again.")


# ---------------------------------------------------------------------------
# Unreal on this machine
# ---------------------------------------------------------------------------

def _engine_root(binary: str) -> str:
    """The ``Engine`` folder above an UnrealEditor binary, or ""."""
    parts = os.path.normpath(binary).split(os.sep)
    if "Engine" not in parts:
        return ""
    return os.sep.join(parts[:len(parts) - parts[::-1].index("Engine")])


def version_of(binary: str) -> tuple[int, ...] | None:
    """(major, minor, patch) from the install's Engine/Build/Build.version."""
    root = _engine_root(binary)
    try:
        with open(os.path.join(root, "Build", "Build.version"), encoding="utf-8") as fh:
            build = json.load(fh)
        return int(build["MajorVersion"]), int(build["MinorVersion"]), int(build.get("PatchVersion") or 0)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _launcher_installs() -> list[str]:
    """Install folders the Epic Games Launcher lists (Windows)."""
    data = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "Epic", "UnrealEngineLauncher",
                        "LauncherInstalled.dat")
    try:
        with open(data, encoding="utf-8") as fh:
            listed = json.load(fh).get("InstallationList") or []
    except (OSError, ValueError, AttributeError):
        return []
    return [str(i.get("InstallLocation")) for i in listed
            if isinstance(i, dict) and str(i.get("AppName", "")).startswith("UE_5") and i.get("InstallLocation")]


def candidates() -> list[str]:
    override = os.environ.get("MIXAR_UNREAL", "")
    if override and os.path.isfile(override):
        return [override]
    if sys.platform == "darwin":
        roots = glob.glob("/Users/Shared/Epic Games/UE_5.*") + glob.glob("/Applications/Epic Games/UE_5.*")
        rel = ("Engine", "Binaries", "Mac", "UnrealEditor.app", "Contents", "MacOS", "UnrealEditor")
    elif sys.platform == "win32":
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        roots = _launcher_installs() + glob.glob(os.path.join(program_files, "Epic Games", "UE_5.*"))
        rel = ("Engine", "Binaries", "Win64", "UnrealEditor.exe")
    else:
        roots = glob.glob(os.path.join(os.path.expanduser("~"), "UnrealEngine*")) + glob.glob("/opt/UnrealEngine*")
        rel = ("Engine", "Binaries", "Linux", "UnrealEditor")
    found = [os.path.join(r, *rel) for r in roots]
    return [p for p in dict.fromkeys(found) if os.path.isfile(p)]


def find_unreal() -> dict | None:
    """The newest Unreal 5.8+ here: {"binary", "version", "root"} or None."""
    best = None
    for binary in candidates():
        version = version_of(binary)
        if version and version[:2] >= UNREAL_MIN and (best is None or version > best["version"]):
            best = {"binary": binary, "version": version, "root": _engine_root(binary)}
    return best


def find_uproject(folder: str) -> str:
    """The .uproject in ``folder``, or ""."""
    found = sorted(glob.glob(os.path.join(folder, "*.uproject")))
    return found[0] if found else ""


# ---------------------------------------------------------------------------
# A new game
# ---------------------------------------------------------------------------

def project_name(name: str) -> str:
    """Unreal's project names are identifiers: letters and digits, starting
    with a letter, at most 20 characters."""
    words = re.findall(r"[A-Za-z0-9]+", name)
    out = "".join(w[:1].upper() + w[1:] for w in words)
    out = re.sub(r"^[0-9]+", "", out)
    return (out or "MyGame")[:20]


def create_project(folder: str, name: str, unreal: dict) -> str:
    """A new third-person game in ``folder`` from the engine's template;
    returns its .uproject. A folder that already holds one is reused."""
    existing = find_uproject(folder)
    if existing:
        return existing
    templates = os.path.join(os.path.dirname(unreal["root"]), "Templates")
    source = os.path.join(templates, TEMPLATE)
    if not os.path.isdir(source):
        raise RuntimeError(f"This Unreal install has no {TEMPLATE} template.")
    os.makedirs(folder, exist_ok=True)
    for part in ("Config", "Content"):
        shutil.copytree(os.path.join(source, part), os.path.join(folder, part), dirs_exist_ok=True)
    for pack in TEMPLATE_PACKS:
        content = os.path.join(templates, "TemplateResources", "High", pack, "Content")
        if os.path.isdir(content):
            shutil.copytree(content, os.path.join(folder, "Content", pack), dirs_exist_ok=True)
    try:
        os.remove(os.path.join(folder, "Config", "TemplateDefs.ini"))
    except OSError:
        pass
    _set_ini(os.path.join(folder, "Config", "DefaultGame.ini"), "[/Script/EngineSettings.GeneralProjectSettings]",
             {"ProjectName": name.replace("\n", " ")[:60],
              "ProjectID": "(A=%d,B=%d,C=%d,D=%d)" % tuple(random.randint(-2**31, 2**31 - 1) for _ in range(4))})
    major, minor = unreal["version"][:2]
    uproject = os.path.join(folder, project_name(name) + ".uproject")
    with open(uproject, "w", encoding="utf-8") as fh:
        json.dump({"FileVersion": 3, "EngineAssociation": f"{major}.{minor}", "Category": "",
                   "Description": "Made with Mixar",
                   "Plugins": [{"Name": "ModelingToolsEditorMode", "Enabled": True, "TargetAllowList": ["Editor"]},
                               {"Name": "GameplayStateTree", "Enabled": True}]},
                  fh, indent="\t")
    return uproject


# ---------------------------------------------------------------------------
# Mixar Link in a project
# ---------------------------------------------------------------------------

def _set_ini(path: str, section: str, values: dict) -> None:
    """Set ``values`` under ``section`` of an Unreal ini, keeping everything else."""
    try:
        with open(path, encoding="utf-8-sig") as fh:
            lines = fh.read().splitlines()
    except OSError:
        lines = []
    start = next((i for i, line in enumerate(lines) if line.strip() == section), -1)
    if start < 0:
        if lines and lines[-1].strip():
            lines.append("")
        lines += [section] + [f"{k}={v}" for k, v in values.items()]
    else:
        end = next((i for i in range(start + 1, len(lines)) if lines[i].strip().startswith("[")), len(lines))
        body = lines[start + 1:end]
        remaining = dict(values)
        for i, line in enumerate(body):
            key = line.split("=", 1)[0].strip()
            if "=" in line and key in remaining:
                body[i] = f"{key}={remaining.pop(key)}"
        while body and not body[-1].strip():
            body.pop()
        body += [f"{k}={v}" for k, v in remaining.items()]
        lines = lines[:start + 1] + body + ([""] if end < len(lines) else []) + lines[end:]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def enable_plugins(uproject: str) -> None:
    """Every plugin Mixar Link needs, enabled in the .uproject; the rest kept."""
    with open(uproject, encoding="utf-8-sig") as fh:
        desc = json.load(fh)
    plugins = desc.get("Plugins")
    if not isinstance(plugins, list):
        plugins = desc["Plugins"] = []
    for name in REQUIRED_PLUGINS:
        entry = next((p for p in plugins if isinstance(p, dict) and p.get("Name") == name), None)
        if entry is None:
            plugins.append({"Name": name, "Enabled": True})
        else:
            entry["Enabled"] = True
    with open(uproject, "w", encoding="utf-8") as fh:
        json.dump(desc, fh, indent="\t")


def _add_ini_line(path: str, section: str, line: str) -> None:
    """``line`` under ``section`` once (an array entry: ``+Key=value``)."""
    try:
        with open(path, encoding="utf-8-sig") as fh:
            lines = fh.read().splitlines()
    except OSError:
        lines = []
    start = next((i for i, x in enumerate(lines) if x.strip() == section), -1)
    if start < 0:
        if lines and lines[-1].strip():
            lines.append("")
        lines += [section, line]
    else:
        end = next((i for i in range(start + 1, len(lines)) if lines[i].strip().startswith("[")), len(lines))
        if any(x.strip() == line for x in lines[start + 1:end]):
            return
        body = lines[start + 1:end]
        while body and not body[-1].strip():
            body.pop()
        lines = lines[:start + 1] + body + [line] + ([""] if end < len(lines) else []) + lines[end:]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def enable_server(project: str) -> None:
    """Unreal's MCP server on at editor start, on Mixar's port and bound to
    the loopback address only, and the editor not throttled while it is in the
    background. The server itself refuses a browser Origin other than
    localhost (DNS rebinding) and has no token, so it is this machine's."""
    settings = os.path.join(project, "Config", "DefaultEditorPerProjectUserSettings.ini")
    _set_ini(settings, MCP_SECTION, {"bAutoStartServer": "True", "ServerPortNumber": str(MCP_PORT)})
    _set_ini(settings, PERFORMANCE_SECTION, {"bThrottleCPUWhenNotForeground": "False"})
    _add_ini_line(os.path.join(project, "Config", "DefaultEngine.ini"), LISTENERS_SECTION, LISTENER_OVERRIDE)


def set_mode(project: str, mode: str) -> None:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    _set_ini(os.path.join(project, "Config", "DefaultMixarLink.ini"), MODE_SECTION, {"ProjectMode": mode})


def install_plugin(uproject: str, progress=None, archive: bytes | None = None, mode: str = "plugin") -> str:
    """Mixar Link for Unreal ``PLUGIN_VERSION`` (or ``archive``) into the
    project's Plugins/, everything it needs enabled; returns its version. A
    previous copy is replaced. A download that is not byte-for-byte the pinned
    release installs nothing."""
    if not uproject.endswith(".uproject") or not os.path.isfile(uproject):
        raise ValueError("That folder is not an Unreal project (no .uproject).")
    project = os.path.dirname(uproject)
    if archive is None:
        if progress:
            progress("Downloading Mixar Link")
        with urllib.request.urlopen(urllib.request.Request(PLUGIN_URL, headers={"User-Agent": "Mixar"}),
                                    timeout=60) as resp:
            archive = resp.read()
        if hashlib.sha256(archive).hexdigest() != PLUGIN_SHA256:
            raise RuntimeError(CHECKSUM_FAILED)
    plugins = os.path.join(project, "Plugins")
    target = os.path.join(plugins, "MixarLink")
    os.makedirs(plugins, exist_ok=True)
    staging = tempfile.mkdtemp(prefix="mixar-link-", dir=plugins)
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            for member in z.namelist():  # only MixarLink/…, never an absolute or .. path
                if not member.startswith("MixarLink/") or ".." in member.split("/"):
                    raise ValueError(f"unexpected file in the plugin archive: {member}")
            z.extractall(staging)
        descriptor = os.path.join(staging, "MixarLink", "MixarLink.uplugin")
        if not os.path.isfile(descriptor):
            raise ValueError("the plugin archive has no MixarLink.uplugin")
        with open(descriptor, encoding="utf-8-sig") as fh:
            version = str(json.load(fh).get("VersionName") or "?")
        if os.path.isdir(target):
            shutil.rmtree(target)
        shutil.move(os.path.join(staging, "MixarLink"), target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    enable_plugins(uproject)
    enable_server(project)
    set_mode(project, mode)
    return version


def open_unreal(unreal: dict, uproject: str) -> subprocess.Popen:
    return subprocess.Popen([unreal["binary"], uproject], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)
