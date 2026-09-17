# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The mic reaches all three surfaces, and reaches them the same way.

Behaviour has ONE owner — the Python session — and the surfaces only say where
the words should go. What is pinned here is that each surface is actually
wired, that none of them grew its own state, and the two properties that are
silently destructive if they regress:

- `target` must be `SKIP_SAVE`. `WM_operator_last_properties_init` refills any
  non-skip property a press did not set from the PREVIOUS press, so one
  unflagged property means a mic clicked in the chat starts dictating into
  whichever node was recorded to an hour ago. The same flag, for the same
  reason, the moodboard's `extend` contract documents.
- Every `draw_prompt_section` caller must pass `context`, or that tab's mic is
  silently absent while every other tab has one.
"""

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock  # noqa: E402

install_bpy_mock()

MODULES = SCRIPTS / "mixar" / "modules"
CPP = ROOT / "src" / "source" / "blender" / "editors"
OPS_PY = MODULES / "voice" / "ui" / "operators" / "voice_ops.py"
HELPERS_PY = MODULES / "moodboard" / "ui" / "sidebar_ui_helpers.py"
FOOTER_CC = CPP / "space_mixie_chat" / "mixie_chat_footer.cc"
NODE_TILE_CC = CPP / "space_mixie" / "mixie_draw_moodboard_node_tile_controls.cc"


# -- the operator ----------------------------------------------------------


def test_the_target_property_is_skip_save():
    tree = ast.parse(OPS_PY.read_text())
    found = False
    for node in ast.walk(tree):
        # Blender's property idiom is an ANNOTATION carrying the call
        # (`target: StringProperty(...)`), so the declaration lives in
        # `annotation` and `value` is None.
        if not isinstance(node, ast.AnnAssign):
            continue
        if getattr(node.target, "id", "") != "target":
            continue
        if not isinstance(node.annotation, ast.Call):
            continue
        found = True
        options = [
            element.value
            for keyword in node.annotation.keywords
            if keyword.arg == "options"
            for element in keyword.value.elts
        ]
        assert "SKIP_SAVE" in options
    assert found, "the toggle operator has no target property"


def test_there_is_one_toggle_operator_every_surface_invokes():
    source = OPS_PY.read_text()
    assert source.count('bl_idname = "mixar.voice_record_toggle"') == 1


def test_unregister_releases_the_microphone():
    """The device outlives Python's module state.

    A reload while recording would otherwise leave the mic open with nothing
    able to stop it.
    """
    source = OPS_PY.read_text()
    assert "def unregister" in source
    assert "shutdown()" in source


# -- surface 1 and 2: the chat composer and the Agent Bubble ---------------


def test_the_chat_footer_places_and_paints_the_mic():
    footer = FOOTER_CC.read_text()
    assert "mixie_chat_voice_add_button(" in footer
    assert "mixie_chat_voice_draw(" in footer


def test_the_bubble_inherits_the_mic_from_the_shared_footer():
    """The Agent Bubble reuses this footer wholesale.

    If the mic were added in a bubble-specific file instead, the two composers
    would need two implementations — which is exactly how the bubble's drop
    handling once diverged.
    """
    bubble = (CPP / "space_agent_bubble" / "space_agent_bubble.cc").read_text()
    assert "mixie_chat_footer_region_init" in bubble


# -- surface 3: the moodboard node tile ------------------------------------


def test_the_node_tile_only_offers_a_mic_where_a_prompt_exists():
    """A mesh-only node has no text field for the words to land in."""
    tile = NODE_TILE_CC.read_text()
    mic_at = tile.index("MIXAR_OT_voice_record_toggle")
    guard_at = tile.rindex('RNA_boolean_get(node, "show_prompt")', 0, mic_at)
    assert guard_at > 0
    # The guard must be the one immediately enclosing the mic, not a distant
    # earlier branch that happens to test the same property.
    assert mic_at - guard_at < 1200


# -- surface 4 (all of them at once): the N-panel tabs ---------------------


def test_the_shared_prompt_drawer_is_the_one_place_the_tab_mic_is_added():
    """One call in the shared helper; the whole mic lives in the voice module.

    That split is also what keeps `sidebar_ui_helpers.py` inside the 500-line
    rule — it was already at 494.
    """
    helpers = HELPERS_PY.read_text()
    # Once as a call: the import line names it too.
    assert helpers.count("draw_prompt_mic(") == 1
    assert len(helpers.splitlines()) <= 500


def test_every_prompt_tab_passes_context_so_none_silently_loses_its_mic():
    missing = []
    for path in sorted((MODULES / "moodboard" / "ui").glob("*.py")):
        source = path.read_text()
        for match in re.finditer(r"draw_prompt_section\(", source):
            start = match.end() - 1
            depth = 0
            index = start
            while index < len(source):
                if source[index] == "(":
                    depth += 1
                elif source[index] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                index += 1
            call = source[match.end():index]
            # The definition itself, not a call.
            if source[source.rfind("\n", 0, match.start()) + 1:match.start()].strip().startswith("def"):
                continue
            if "context=" not in call:
                missing.append(f"{path.name}:{source[:match.start()].count(chr(10)) + 1}")
    assert not missing, f"prompt sections drawn without context (no mic): {missing}"


def test_the_python_drawer_hides_itself_when_the_build_cannot_record():
    """A dead button is worse than none."""
    drawer = (MODULES / "voice" / "ui" / "voice_button.py").read_text()
    assert "mixar_audio_available" in drawer


def test_a_recording_bound_elsewhere_does_not_light_up_another_tabs_mic():
    """Two lit mics invite a press that can only report "still transcribing"."""
    drawer = (MODULES / "voice" / "ui" / "voice_button.py").read_text()
    assert "mixar_voice_target" in drawer
    assert "mine" in drawer
