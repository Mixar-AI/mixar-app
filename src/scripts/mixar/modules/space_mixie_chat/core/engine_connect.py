# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Connecting Mixar to a game engine: the logic behind the composer's engine
chip (UI in ``ui/engine_chip.py``; the link itself is ``engine_link``).

- ``server_supports()``: whether the connected Mixar server has the engine
  tools (it lists ``engine_link_v1`` in its handshake reply). Until one
  does, the chip is hidden and nothing here reads editors or connects.
- ``state()``: what the chip shows. Live editors come from ``engine_link``
  (their discovery files), the picked one is remembered across launches, and
  the read runs off the main thread (``refresh_async``), because a stale
  discovery file costs a socket timeout.
- ``find_godot()`` / ``download_godot()``: a Godot 4.5+ on this machine, or
  the official ``GODOT_VERSION`` build (refused unless it matches
  ``GODOT_SHA256``) downloaded into ~/Applications (macOS) or
  ~/.mixar/engines (elsewhere).
- ``install_addon(project)``: Mixar Link ``ADDON_VERSION`` (``ADDON_URL``,
  refused unless it matches ``ADDON_SHA256``) unpacked into ``<project>/addons/mixar_link`` and enabled
  in ``project.godot``; ``create_project`` makes a new one first.
- ``connect(project)``: install, open Godot on the project, wait for its
  discovery file. ``connect(project, engine="unreal")`` does the same for
  Unreal Engine 5.8+ through ``unreal_setup`` (found, never downloaded; a new
  game is the engine's third-person template).

Nothing here leaves the machine except the two downloads; no path is ever
sent to the backend (``engine_context`` carries names only).
"""

from __future__ import annotations

import glob
import hashlib
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile

from . import engine_link, unreal_setup

# Mixar Link for Godot: one exact release, checked before it is installed.
# A new release is these two lines (sha256 of the release's mixar_link.zip).
ADDON_VERSION = "0.4.0"
ADDON_SHA256 = "d4fef97bb6b846fc19e4d4b55e6d02441fc1496c99b79b11feff1c9f07bf7409"
ADDON_REPO = "Mixar-AI/mixar-engine-godot"
ADDON_URL = f"https://github.com/{ADDON_REPO}/releases/download/v{ADDON_VERSION}/mixar_link.zip"
# The Godot editor Mixar downloads when none is installed, and the sha256 of
# each official build it may fetch, by the asset's platform part
# (``Godot_v<version>-stable_<part>`` on godotengine/godot's release). A new
# Godot is the version plus these hashes; a platform missing here is never
# downloaded.
GODOT_VERSION = "4.7.2"
GODOT_SHA256 = {
    "macos.universal.zip": "c58a24e31d720be9d62f60cb5627c4e695fb72f21b0cfe1bc9ccaa9a3b3ba63e",
    "win64.exe.zip": "731980f9608d61333e5baf54a2ef17210acc7a538446c0cb9969f002aca1e953",
    "windows_arm64.exe.zip": "2d206e0b1d2366eb3508971c670c52333dcd7218b818102d77ca7ceaa86892ba",
    "linux.x86_64.zip": "cadd3204e728a35d3f13adb7fd0d7902636b79f6b95c40c265eb73b6c35329e4",
    "linux.arm64.zip": "5dd0d86405cf7e8adf79fb6377b38ba682a2846cb378ffe5364f38c01ad29b9d",
}
GODOT_MIN = (4, 5)
GODOT_RELEASES = "https://github.com/godotengine/godot/releases/download"
CHECKSUM_FAILED = ("The downloaded {what} is not the release Mixar expects (checksum mismatch); "
                   "nothing was installed. Try again, or update Mixar.")
NO_GODOT_BUILD = ("Mixar has no Godot download for this machine; install Godot 4.5 or newer from "
                  "godotengine.org, then connect again.")
PLUGIN_CFG = "res://addons/mixar_link/plugin.cfg"
CONNECT_TIMEOUT_S = 120.0
# Unreal's first open of a project compiles its shaders: minutes, not seconds.
UNREAL_CONNECT_TIMEOUT_S = 1800.0
# The engines the chip's dropdown lists.
ENGINES = (
    {"key": "godot", "label": "Godot", "available": True},
    {"key": "unreal", "label": "Unreal Engine", "available": True},
    {"key": "uefn", "label": "UEFN", "available": False},
)

# Sent in the agent handshake and listed back by a server with the engine
# tools (socket_connection); both ends use the same name.
ENGINE_LINK_CAPABILITY = "engine_link_v1"

# ``engine``: which engine ``busy`` / ``error`` belong to (the connect running or failed).
_state: dict = {"connected": False, "editors": [], "selected": "", "busy": "", "error": "", "engine": "",
                "at": 0.0}
_lock = threading.Lock()
_refreshing = False
_server_supports = False


# ---------------------------------------------------------------------------
# Whether the server has the engine tools
# ---------------------------------------------------------------------------

def set_server_capabilities(capabilities) -> None:
    """From each handshake reply (socket_connection). Only an answering
    server changes it: while the socket is offline the last answer stands."""
    global _server_supports
    _server_supports = ENGINE_LINK_CAPABILITY in (capabilities or ())


def server_supports() -> bool:
    return _server_supports


# ---------------------------------------------------------------------------
# What the chip shows
# ---------------------------------------------------------------------------

def state() -> dict:
    with _lock:
        return dict(_state)


def _set(**changes) -> None:
    with _lock:
        _state.update(changes)


def refresh() -> dict:
    """Read the live editors now (blocking: call from a thread)."""
    found = engine_link.adapters()
    editors = [engine_link.public(i) for i in found]
    chosen = engine_link.public(engine_link.choose(found))["id"] if found else ""
    _set(connected=bool(found), editors=editors, selected=chosen, at=time.time())
    return state()


def refresh_async() -> None:
    """Refresh in a daemon thread; a refresh already running is not doubled.
    Nothing to read while the server has no engine tools."""
    global _refreshing
    if _refreshing or not server_supports():
        return
    _refreshing = True

    def run():
        global _refreshing
        try:
            refresh()
        except Exception:  # noqa: BLE001 - the chip must never break the composer
            pass
        finally:
            _refreshing = False

    threading.Thread(target=run, name="mixar-engine-refresh", daemon=True).start()


def select(editor_id: str) -> None:
    engine_link.select(editor_id)
    _set(selected=editor_id)


def chip_label(st: dict | None = None) -> str:
    st = st or state()
    if st.get("busy"):
        return st["busy"]
    chosen = next((e for e in st.get("editors") or [] if e["id"] == st.get("selected")), None)
    if chosen:
        return f"{chosen.get('engine', '').title()} · {chosen.get('project_name') or 'project'}"
    return "Connect engine"


def engine_context() -> dict | None:
    """Names only, for the agent: which engine and project are connected."""
    if not server_supports():
        return None
    st = state()
    chosen = next((e for e in st.get("editors") or [] if e["id"] == st.get("selected")), None)
    if not chosen:
        return None
    return {"engine": chosen.get("engine"), "version": chosen.get("version"),
            "project_name": chosen.get("project_name"), "adapter_version": chosen.get("adapter_version")}


# ---------------------------------------------------------------------------
# Godot on this machine
# ---------------------------------------------------------------------------

def _version_of(binary: str) -> tuple[int, ...] | None:
    try:
        out = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.match(r"\s*(\d+)\.(\d+)(?:\.(\d+))?", out or "")
    return tuple(int(g or 0) for g in match.groups()) if match else None


def godot_candidates() -> list[str]:
    home = os.path.expanduser("~")
    # A developer's or a QA rig's Godot, ahead of the installed ones.
    override = os.environ.get("MIXAR_GODOT", "")
    if override and os.path.isfile(override):
        return [override]
    if sys.platform == "darwin":
        apps = glob.glob("/Applications/Godot*.app") + glob.glob(os.path.join(home, "Applications", "Godot*.app"))
        found = [os.path.join(a, "Contents", "MacOS", "Godot") for a in apps]
    elif sys.platform == "win32":
        found = glob.glob(os.path.join(home, ".mixar", "engines", "godot*", "Godot*.exe")) + \
            glob.glob(os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Godot*", "Godot*.exe"))
    else:
        found = glob.glob(os.path.join(home, ".mixar", "engines", "godot*", "Godot*"))
    for name in ("godot4", "godot"):
        path = shutil.which(name)
        if path:
            found.append(path)
    return [p for p in dict.fromkeys(found) if os.path.isfile(p)]


def find_godot() -> dict | None:
    """The newest Godot 4.5+ here: {"binary", "version"} or None."""
    best = None
    for binary in godot_candidates():
        version = _version_of(binary)
        if version and version[:2] >= GODOT_MIN and (best is None or version > best["version"]):
            best = {"binary": binary, "version": version}
    return best


def _godot_asset() -> tuple[str, str]:
    """(release asset platform part, install folder) for this platform and CPU."""
    home = os.path.expanduser("~")
    arm = platform.machine().lower() in ("arm64", "aarch64")
    if sys.platform == "darwin":
        return "macos.universal.zip", os.path.join(home, "Applications")
    if sys.platform == "win32":
        return (f"{'windows_arm64' if arm else 'win64'}.exe.zip",
                os.path.join(home, ".mixar", "engines", f"godot-{GODOT_VERSION}"))
    return (f"linux.{'arm64' if arm else 'x86_64'}.zip",
            os.path.join(home, ".mixar", "engines", f"godot-{GODOT_VERSION}"))


def download_godot(progress=None) -> dict:
    """The official Godot build for this platform, checked and unpacked;
    returns find_godot()."""
    part, dest = _godot_asset()
    expected = GODOT_SHA256.get(part)
    if not expected:
        raise RuntimeError(NO_GODOT_BUILD)
    asset = f"Godot_v{GODOT_VERSION}-stable_{part}"
    archive = os.path.join(tempfile.mkdtemp(prefix="mixar-godot-"), asset)
    try:
        _download(f"{GODOT_RELEASES}/{GODOT_VERSION}-stable/{asset}", archive, progress, "Downloading Godot",
                  sha256=expected)
    except Exception:
        shutil.rmtree(os.path.dirname(archive), ignore_errors=True)
        raise
    os.makedirs(dest, exist_ok=True)
    if sys.platform == "darwin":
        # ditto keeps the bundle's symlinks and permissions; zipfile does not.
        subprocess.run(["ditto", "-x", "-k", archive, dest], check=True)
    else:
        with zipfile.ZipFile(archive) as z:
            z.extractall(dest)
        for path in glob.glob(os.path.join(dest, "Godot*")):
            os.chmod(path, 0o755)
    shutil.rmtree(os.path.dirname(archive), ignore_errors=True)
    found = find_godot()
    if not found:
        raise RuntimeError("Godot was downloaded but does not start.")
    return found


def _download(url: str, path: str, progress, label: str, sha256: str) -> None:
    """``url`` into ``path``, only when its bytes hash to ``sha256``."""
    digest = hashlib.sha256()
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mixar"}), timeout=60) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with open(path + ".part", "wb") as out:
            while chunk := resp.read(1 << 20):
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress and total:
                    progress(f"{label} {int(100 * done / total)}%")
    if digest.hexdigest() != sha256:
        os.remove(path + ".part")
        raise RuntimeError(CHECKSUM_FAILED.format(what="Godot"))
    os.replace(path + ".part", path)


# ---------------------------------------------------------------------------
# The add-on in a project
# ---------------------------------------------------------------------------

def create_project(folder: str, name: str) -> str:
    """A new, empty Godot 4 project in ``folder`` (created)."""
    os.makedirs(folder, exist_ok=True)
    cfg = os.path.join(folder, "project.godot")
    if not os.path.exists(cfg):
        with open(cfg, "w", encoding="utf-8") as fh:
            fh.write('config_version=5\n\n[application]\n\nconfig/name="%s"\n' % name.replace('"', "'"))
    return folder


def enable_plugin(project: str) -> None:
    """Add Mixar Link to ``[editor_plugins] enabled`` in project.godot."""
    cfg = os.path.join(project, "project.godot")
    text = open(cfg, encoding="utf-8").read()
    if PLUGIN_CFG in text:
        return
    line = re.search(r'^enabled=PackedStringArray\((.*)\)\s*$', text, re.M)
    if line:
        items = [i for i in (line.group(1).strip(),) if i]
        new = f'enabled=PackedStringArray({", ".join(items + [json.dumps(PLUGIN_CFG)])})'
        text = text[:line.start()] + new + text[line.end():]
    elif re.search(r"^\[editor_plugins\]\s*$", text, re.M):
        text = re.sub(r"^\[editor_plugins\]\s*$", f'[editor_plugins]\n\nenabled=PackedStringArray("{PLUGIN_CFG}")',
                      text, count=1, flags=re.M)
    else:
        text = text.rstrip("\n") + f'\n\n[editor_plugins]\n\nenabled=PackedStringArray("{PLUGIN_CFG}")\n'
    with open(cfg, "w", encoding="utf-8") as fh:
        fh.write(text)


def install_addon(project: str, progress=None, archive: bytes | None = None) -> str:
    """Mixar Link ``ADDON_VERSION`` (or ``archive``) into the project,
    enabled; returns its version. A previous copy is replaced. A download that
    is not byte-for-byte the pinned release installs nothing."""
    if not os.path.isfile(os.path.join(project, "project.godot")):
        raise ValueError("That folder is not a Godot project (no project.godot).")
    if archive is None:
        if progress:
            progress("Downloading Mixar Link")
        with urllib.request.urlopen(urllib.request.Request(ADDON_URL, headers={"User-Agent": "Mixar"}),
                                    timeout=60) as resp:
            archive = resp.read()
        if hashlib.sha256(archive).hexdigest() != ADDON_SHA256:
            raise RuntimeError(CHECKSUM_FAILED.format(what="Mixar Link"))
    addons = os.path.join(project, "addons")
    target = os.path.join(addons, "mixar_link")
    staging = tempfile.mkdtemp(prefix="mixar-link-", dir=project)
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            for member in z.namelist():  # only mixar_link/…, never an absolute or .. path
                if not member.startswith("mixar_link/") or ".." in member.split("/"):
                    raise ValueError(f"unexpected file in the add-on archive: {member}")
            z.extractall(staging)
        if not os.path.isfile(os.path.join(staging, "mixar_link", "plugin.cfg")):
            raise ValueError("the add-on archive has no plugin.cfg")
        os.makedirs(addons, exist_ok=True)
        if os.path.isdir(target):
            shutil.rmtree(target)
        shutil.move(os.path.join(staging, "mixar_link"), target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    enable_plugin(project)
    version = re.search(r'^version="([^"]+)"', open(os.path.join(target, "plugin.cfg"), encoding="utf-8").read(), re.M)
    return version.group(1) if version else "?"


def open_godot(binary: str, project: str) -> subprocess.Popen:
    return subprocess.Popen([binary, "--editor", "--path", project], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)


def connect(project: str, *, engine: str = "godot", new_name: str | None = None, progress=None) -> dict:
    """The whole one-click flow (blocking; run in a thread): the engine found
    (Godot downloaded when missing), the project made if asked, Mixar Link
    installed and enabled, the editor opened on it, its link awaited and
    selected."""
    say = progress or (lambda text: None)
    if engine == "unreal":
        return _connect_unreal(project, new_name, say)
    godot = find_godot() or download_godot(say)
    if new_name:
        create_project(project, new_name)
    version = install_addon(project, say)
    say("Opening Godot")
    proc = open_godot(godot["binary"], project)
    return _await_link(proc, "godot", CONNECT_TIMEOUT_S, version)


def _connect_unreal(folder: str, new_name: str | None, say) -> dict:
    unreal = unreal_setup.find_unreal()
    if not unreal:
        raise RuntimeError(unreal_setup.NOT_INSTALLED)
    if new_name:
        say("Making the game project")
        uproject = unreal_setup.create_project(folder, new_name, unreal)
    else:
        uproject = unreal_setup.find_uproject(folder)
    if not uproject:
        raise ValueError("That folder is not an Unreal project (it has no .uproject).")
    version = unreal_setup.install_plugin(uproject, say, mode="owned" if new_name else "plugin")
    say("Opening Unreal (the first open compiles shaders)")
    proc = unreal_setup.open_unreal(unreal, uproject)
    return _await_link(proc, "unreal", UNREAL_CONNECT_TIMEOUT_S, version)


def _await_link(proc, engine: str, timeout: float, version: str) -> dict:
    label = "Unreal" if engine == "unreal" else "Godot"
    deadline = time.time() + timeout
    while time.time() < deadline:
        mine = [i for i in engine_link.adapters(engine) if int(i.get("pid") or 0) == proc.pid]
        if mine:
            editor = engine_link.public(mine[0])
            select(editor["id"])
            refresh()
            return {"editor": editor, "addon_version": version}
        if proc.poll() is not None:
            raise RuntimeError(f"{label} closed before it connected.")
        time.sleep(0.5)
    raise RuntimeError(f"{label} opened but Mixar Link did not connect (is the plugin enabled?).")


def connect_async(project: str, *, engine: str = "godot", new_name: str | None = None) -> None:
    """``connect`` in a thread; progress and errors land in ``state()``.
    Nothing happens while the server has no engine tools."""
    if not server_supports():
        return

    def run():
        try:
            _set(busy="Connecting…", error="", engine=engine)
            connect(project, engine=engine, new_name=new_name, progress=lambda text: _set(busy=text))
            _set(busy="")
        except Exception as exc:  # noqa: BLE001 - shown on the chip
            _set(busy="", error=str(exc)[:200])

    threading.Thread(target=run, name="mixar-engine-connect", daemon=True).start()
