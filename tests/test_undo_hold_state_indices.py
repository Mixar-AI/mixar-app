# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The C-side undo hold (per-tab undo M4, ``BKE_undo_tab_scene_is_working`` in
``src/source/blender/blenkernel/intern/undo_tabs.cc``) reads the chat module's
``mixie_chat_state`` enum as the IDProperty int it is stored as: the ITEM INDEX
of ``SESSION_STATE_ITEMS``. ``UNDO_TAB_STATE_BUSY`` / ``_MODIFYING`` /
``_AWAITING_INPUT`` in ``BKE_undo_tabs.hh`` are 3 / 4 / 5. Reordering the items
would silently move the hold; this pins both sides to each other.
"""

import importlib.util
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[1]
CONSTANTS = REPO / "src/scripts/mixar/modules/space_mixie_chat/constants.py"
HEADER = REPO / "src/source/blender/blenkernel/BKE_undo_tabs.hh"


def _session_state_items():
    spec = importlib.util.spec_from_file_location("mixie_constants", CONSTANTS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return [item[0] for item in module.SESSION_STATE_ITEMS]


def _c_constants():
    text = HEADER.read_text()
    return {name: int(value) for name, value in
            re.findall(r"constexpr int UNDO_TAB_STATE_(\w+) = (\d+);", text)}


def test_c_hold_indices_match_the_python_enum_order():
    items = _session_state_items()
    c = _c_constants()
    assert c == {"BUSY": items.index("BUSY"), "MODIFYING": items.index("MODIFYING"),
                 "AWAITING_INPUT": items.index("AWAITING_INPUT")}


def test_idle_and_offline_are_not_working_states():
    items = _session_state_items()
    c = _c_constants()
    for quiet in ("OFFLINE", "CONNECTING", "IDLE"):
        assert items.index(quiet) not in c.values()
