# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Write the picker's WindowManager mirrors (`ui/properties/agent_model_props.py`).

One function, `apply_to_wm`, called from every place the inputs change:
`credential_state.apply_to_wm`, `preference_state.apply_to_wm`, the catalog
load (`models_cache._redraw`), the first draw after start-up and every change
of the signed-in / guest flags (their RNA updates), and the start and end of
a hosted pick (`preference_state.begin_mutation` / `end_mutation`) or a
dialog save / removal (`byok_client._track`): the chip's BUSY state is what
the island card words its gate from. It reads the three mirrors, runs
`picker` and writes the strings the C++ chip and popup draw.
The island card (agent_ui_model_card.cc) owns its open tab and its thinking
disclosure; it opens on the source in use every time.
"""

from mixar.config.logging_config import get_logger

from . import picker

logger = get_logger(__name__)

def apply_to_wm(wm=None) -> None:
    try:
        import bpy

        target = wm if wm is not None else bpy.context.window_manager
    except Exception:
        return
    if target is None or not hasattr(target, "mixar_agent_rows"):
        return  # properties not registered yet; the next apply catches up
    try:
        from . import byok_client, credential_state, model_suggestions, preference_state

        state = picker.picker_state(
            credential_state.snapshot(), preference_state.snapshot(),
            guest=bool(getattr(target, "mixie_chat_is_guest", False)),
            signed_in=bool(getattr(target, "mixie_chat_is_logged_in", True)),
            pending=credential_state.pending(), switching=credential_state.switching(),
            busy=byok_client.mutation_in_flight() or preference_state.mutation_pending())
        tabs = picker.build_tabs(state)
        rows = picker.build_rows(state, model_suggestions.get_platform_models())
        chip = picker.chip(state)
    except Exception as exc:  # noqa: BLE001 — a mirror write must never break a callback
        logger.debug("Picker mirror skipped: %s", exc)
        return
    try:
        target.mixar_agent_source = chip["source"]
        target.mixar_agent_source_label = chip["label"]
        target.mixar_agent_chip_name = chip["name"]
        target.mixar_agent_source_state = chip["state"]
        target.mixar_agent_tabs = picker.encode_tabs(tabs)
        target.mixar_agent_rows = picker.encode_rows(rows)
    except Exception as exc:  # noqa: BLE001 — registered in a later auto-discovery batch
        logger.debug("Picker mirror not written: %s", exc)
