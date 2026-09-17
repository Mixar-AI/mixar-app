# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The seams where the voice feature crosses from Python into C++.

Every one of these is a string or a number duplicated in two languages, and
every one of them fails SILENTLY if the copies drift:

- an RNA name the C++ reads but Python never registers reads as "idle", so the
  mic simply never lights up;
- a state identifier spelled differently in the two halves does the same;
- a target string built differently in C++ than in Python addresses a field
  that does not exist, and the transcript is dropped with a message;
- a Python recording cap above the C++ buffer's cap shows a clock ticking over
  audio nobody captured.

The C++ half cannot be imported, so these read the sources. That is the same
approach `tests/test_agent_bubble_linux_controls.py` and the moodboard graph
tests take for contracts that span the language boundary.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock  # noqa: E402

install_bpy_mock()

from mixar.modules.voice import constants  # noqa: E402

CPP = ROOT / "src" / "source" / "blender"
AUDIO_HH = CPP / "editors" / "include" / "ED_mixar_audio.hh"
AUDIO_UI_HH = CPP / "editors" / "include" / "ED_mixar_audio_ui.hh"
STATE_CC = CPP / "editors" / "mixar_audio" / "mixar_audio_state.cc"
CAPTURE_CC = CPP / "editors" / "mixar_audio" / "mixar_audio_capture.cc"
WAV_CC = CPP / "editors" / "mixar_audio" / "mixar_audio_wav.cc"
RNA_CC = CPP / "makesrna" / "intern" / "rna_wm_mixar.cc"
CHAT_VOICE_CC = CPP / "editors" / "space_mixie_chat" / "mixie_chat_voice.cc"
NODE_TILE_CC = (
    CPP / "editors" / "space_mixie" / "mixie_draw_moodboard_node_tile_controls.cc"
)
PROPS_PY = (
    SCRIPTS / "mixar" / "modules" / "voice" / "ui" / "properties" / "voice_props.py"
)


def _define(path: Path, name: str) -> int:
    match = re.search(rf"#define\s+{name}\s+(\d+)", path.read_text())
    assert match, f"{name} is not defined in {path.name}"
    return int(match.group(1))


# -- the recording ceiling -------------------------------------------------


def test_the_python_cap_never_exceeds_the_cpp_buffer():
    """The C++ buffer simply stops growing at its own cap.

    A higher Python cap would leave the clock running and the waveform moving
    over audio that was never captured — the recording would look longer than
    the file the backend receives, and the user would be billed for the file.
    """
    cpp_cap = _define(AUDIO_HH, "MIXAR_AUDIO_MAX_SECONDS")
    assert constants.MAX_RECORDING_SECONDS <= cpp_cap


def test_the_capture_format_is_the_one_the_wav_header_declares():
    """The backend measures duration as data-size over byte-rate.

    If the writer declared a different rate than the device captured at, every
    clip would be billed at the wrong length and Whisper would hear it at the
    wrong speed.
    """
    wav = WAV_CC.read_text()
    assert "MIXAR_AUDIO_SAMPLE_RATE" in wav
    assert "MIXAR_AUDIO_CHANNELS" in wav
    # Neither may be written as a literal beside the macro.
    assert "16000" not in wav


def test_the_capture_device_is_configured_from_the_same_macros():
    capture = CAPTURE_CC.read_text()
    assert "config.sampleRate = MIXAR_AUDIO_SAMPLE_RATE" in capture
    assert "config.capture.channels = MIXAR_AUDIO_CHANNELS" in capture


# -- the RNA mirror --------------------------------------------------------


def test_every_property_cpp_reads_is_one_python_registers():
    cpp_names = set(re.findall(r'"(mixar_voice_\w+)"', STATE_CC.read_text()))
    registered = set(re.findall(r"WindowManager\.(mixar_voice_\w+)", PROPS_PY.read_text()))
    assert cpp_names, "the C++ reader names no voice properties at all"
    assert cpp_names <= registered


def test_the_capture_properties_and_functions_exist_in_rna():
    """The session calls these by name; a typo reads as a missing attribute."""
    rna = RNA_CC.read_text()
    for name in (
        "mixar_audio_available",
        "mixar_audio_recording",
        "mixar_audio_level",
        "mixar_audio_duration",
        "mixar_audio_record_start",
        "mixar_audio_record_stop",
        "mixar_audio_record_cancel",
    ):
        assert f'"{name}"' in rna, f"{name} is not exposed on WindowManager"


def test_the_session_only_calls_capture_rna_that_exists():
    session_py = (
        SCRIPTS / "mixar" / "modules" / "voice" / "core" / "session.py"
    ).read_text()
    rna = RNA_CC.read_text()
    for used in set(re.findall(r"mixar_audio_\w+", session_py)):
        assert f'"{used}"' in rna, f"session.py calls {used}, which RNA does not define"


# -- state identifiers -----------------------------------------------------


def test_cpp_compares_state_identifiers_python_actually_registers():
    state_cc = STATE_CC.read_text()
    compared = set(re.findall(r'STREQ\(identifier, "(\w+)"\)', state_cc))
    python_states = {
        constants.STATE_RECORDING,
        constants.STATE_TRANSCRIBING,
        constants.STATE_ERROR,
        constants.STATE_IDLE,
    }
    assert compared, "the C++ reader compares no identifiers"
    assert compared <= python_states


def test_cpp_reads_the_state_by_identifier_never_by_index():
    """An enum persists as an INDEX.

    Reading the integer would silently repoint every state the moment an item
    is inserted into the list — the same trap the moodboard graph contract
    documents for service/model dropdowns.
    """
    state_cc = STATE_CC.read_text()
    assert "RNA_property_enum_identifier" in state_cc


# -- target strings --------------------------------------------------------


def test_the_chat_footer_addresses_the_target_python_resolves():
    chat = CHAT_VOICE_CC.read_text()
    assert f'"target", "{constants.TARGET_CHAT}"' in chat
    assert f'ED_mixar_voice_target_is(C, "{constants.TARGET_CHAT}")' in chat


def test_the_node_tile_builds_the_same_node_target_prefix_python_parses():
    tile = NODE_TILE_CC.read_text()
    match = re.search(r'BLI_snprintf\(voice_target, sizeof\(voice_target\), "([^"]+)"', tile)
    assert match, "the node tile does not build a voice target"
    assert match.group(1) == f"{constants.TARGET_NODE_PREFIX}%s"


def test_both_cpp_surfaces_invoke_the_one_python_operator():
    """Behaviour has a single owner; the surfaces only say where words go."""
    for path in (CHAT_VOICE_CC, NODE_TILE_CC):
        assert "MIXAR_OT_voice_record_toggle" in path.read_text()


# -- reading RNA strings safely --------------------------------------------


def test_the_target_string_is_read_bounded():
    """`RNA_property_string_get` is strcpy-shaped.

    `mixar_voice_target` carries no `maxlen`, so a raw read into a stack buffer
    is an overrun — the same class of bug the chat's slot reader exists for.
    """
    state_cc = STATE_CC.read_text()
    assert "RNA_property_string_length" in state_cc
    assert "RNA_property_string_get_alloc" in state_cc


# -- the painter's independence --------------------------------------------


def test_the_glyph_painter_takes_its_level_rather_than_reading_the_engine():
    """Two surfaces sample the meter at different moments.

    A painter that read the atomics itself would let one frame show two
    different levels for the same recording.
    """
    header = AUDIO_UI_HH.read_text()
    assert "float level" in header
    glyph = (CPP / "editors" / "mixar_audio" / "mixar_audio_glyph.cc").read_text()
    assert "ED_mixar_audio_level()" not in glyph


def test_no_colour_literal_omits_its_alpha():
    """A three-value float[4] initializer zero-fills alpha.

    The shape then draws completely invisible with no other symptom — exactly
    how the account card's quota bar once disappeared.
    """
    glyph = (CPP / "editors" / "mixar_audio" / "mixar_audio_glyph.cc").read_text()
    for match in re.finditer(r"float\s+\w+\[4\]\s*=\s*\{([^}]*)\}", glyph):
        values = [part for part in match.group(1).split(",") if part.strip()]
        assert len(values) == 4, f"colour literal with {len(values)} components: {match.group(0)}"
