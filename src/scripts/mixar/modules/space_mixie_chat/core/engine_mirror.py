# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The engine chip's WindowManager mirror (``wm.mixar_engine_*``), written from
``engine_connect.state()`` and read by the C++ chip and card
(agent_ui_engine.cc, agent_ui_model_card*.cc with the engine Source).

The card's wire format is the model card's (byok/core/picker.py): records split
by U+001E, fields by U+001F.
- tab:  ``id|label|enabled|cost|note|heading|action``
- row:  ``tab|kind|label|meta|current|enabled|provider|model|thinking``
Here a row's ``model`` field carries the editor id (``godot-<pid>``) that
``MIXAR_OT_engine_pick`` receives as ``editor``.
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


def build(st: dict | None = None) -> dict:
    """The mirror's five strings for ``st`` (default: the live state)."""
    st = st if st is not None else engine_connect.state()
    tabs = []
    for engine in engine_connect.ENGINES:
        key = engine["key"].upper()
        if engine["available"]:
            if st.get("busy"):
                note = st["busy"]
            elif st.get("error"):
                note = f"Could not connect: {st['error']}"
            elif not st.get("connected"):
                note = ("No Godot editor is connected. Connect Godot installs Mixar Link into a "
                        "project and opens it; the agent then builds your game there.")
            else:
                note = ""
            tabs.append(_record(key, engine["label"], 1, "", note, "Connected editors", ""))
        else:
            tabs.append(_record(key, engine["label"], 0, "", "Coming soon", "", ""))
    rows = []
    for editor in st.get("editors") or []:
        if editor.get("engine") != "godot":
            continue
        version = str(editor.get("version") or "").split("-")[0]
        meta = " · ".join(x for x in (f"Godot {version}" if version else "Godot",
                                           f"Link {editor.get('adapter_version')}" if editor.get("adapter_version") else "")
                               if x)
        rows.append(_record("GODOT", "model", editor.get("project_name") or "Untitled project", meta,
                            int(editor.get("id") == st.get("selected")), 1, "", editor.get("id", ""), ""))
    rows.append(_record("GODOT", "footer", "Connect Godot…", "", 0, int(not st.get("busy")), "", "connect", ""))
    return {
        "mixar_engine_chip_name": engine_connect.chip_label(st),
        "mixar_engine_state": chip_state(st),
        "mixar_engine_tab": "GODOT",
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
