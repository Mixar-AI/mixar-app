# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The engine chip's WindowManager mirror (``wm.mixar_engine_*``), written from
``engine_connect.state()`` and read by the C++ chip and card
(agent_ui_engine.cc, agent_ui_model_card*.cc with the engine Source).

The card's wire format is the model card's (byok/core/picker.py): records split
by U+001E, fields by U+001F.
- tab:  ``id|label|enabled|cost|note|heading|action``
- row:  ``tab|kind|label|meta|current|enabled|provider|model|thinking``
Each engine is a tab (GODOT, UNREAL, …). A row's ``model`` field carries the
editor id (``godot-<pid>``, ``unreal-<pid>``) that ``MIXAR_OT_engine_pick``
receives as ``editor``; a tab's footer runs ``MIXAR_OT_engine_connect`` with
that tab as ``engine``.
"""

from __future__ import annotations

from . import engine_connect

RS, FS = "\x1e", "\x1f"
STATE_PROPS = ("mixar_engine_chip_name", "mixar_engine_state", "mixar_engine_tab",
               "mixar_engine_tabs", "mixar_engine_rows")


def _record(*fields) -> str:
    return FS.join(str(f).replace(RS, " ").replace(FS, " ") for f in fields)


def chip_state(st: dict) -> str:
    if st.get("busy"):
        return "BUSY"
    if st.get("error"):
        return "ERROR"
    return "CONNECTED" if st.get("connected") else "OFF"


ENGINE_NAMES = {"godot": "Godot", "unreal": "Unreal"}
NOT_CONNECTED = {
    "godot": ("No Godot editor is connected. Connect Godot installs Mixar Link into a project and "
              "opens it; the agent then builds your game there."),
    "unreal": ("No Unreal editor is connected. Connect Unreal installs Mixar Link into a project "
               "(Unreal Engine 5.8+) and opens it; the agent then builds your game there."),
}


def _note(engine: str, st: dict) -> str:
    """The tab's line: this engine's connect in progress or failed, else a
    hint while none of its editors is live."""
    mine = (st.get("engine") or "godot") == engine
    if st.get("busy") and mine:
        return st["busy"]
    if st.get("error") and mine:
        return f"Could not connect: {st['error']}"
    if not any(e.get("engine") == engine for e in st.get("editors") or []):
        return NOT_CONNECTED.get(engine, "")
    return ""


def _current_tab(st: dict) -> str:
    """The tab the card opens on: the engine being connected, else the chosen
    editor's, else Godot."""
    if st.get("busy") or st.get("error"):
        return (st.get("engine") or "godot").upper()
    chosen = next((e for e in st.get("editors") or [] if e.get("id") == st.get("selected")), None)
    return str(chosen.get("engine") if chosen else "godot").upper()


def build(st: dict | None = None) -> dict:
    """The mirror's five strings for ``st`` (default: the live state)."""
    st = st if st is not None else engine_connect.state()
    tabs, rows = [], []
    for engine in engine_connect.ENGINES:
        key = engine["key"].upper()
        if not engine["available"]:
            tabs.append(_record(key, engine["label"], 0, "", "Coming soon", "", ""))
            continue
        tabs.append(_record(key, engine["label"], 1, "", _note(engine["key"], st), "Connected editors", ""))
        name = ENGINE_NAMES.get(engine["key"], engine["label"])
        for editor in st.get("editors") or []:
            if editor.get("engine") != engine["key"]:
                continue
            version = str(editor.get("version") or "").split("-")[0]
            meta = " · ".join(x for x in (f"{name} {version}" if version else name,
                                               f"Link {editor.get('adapter_version')}" if editor.get("adapter_version") else "")
                                   if x)
            rows.append(_record(key, "model", editor.get("project_name") or "Untitled project", meta,
                                int(editor.get("id") == st.get("selected")), 1, "", editor.get("id", ""), ""))
        rows.append(_record(key, "footer", f"Connect {name}…", "", 0, int(not st.get("busy")), "", "connect", ""))
    return {
        "mixar_engine_chip_name": engine_connect.chip_label(st),
        "mixar_engine_state": chip_state(st),
        "mixar_engine_tab": _current_tab(st),
        "mixar_engine_tabs": RS.join(tabs),
        "mixar_engine_rows": RS.join(rows),
    }


def apply_to_wm(wm) -> bool:
    """Write the mirror; True when anything changed (the caller redraws)."""
    values = build()
    changed = False
    for name, value in values.items():
        if hasattr(wm, name) and getattr(wm, name) != value:
            setattr(wm, name, value)
            changed = True
    return changed
