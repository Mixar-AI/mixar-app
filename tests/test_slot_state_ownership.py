# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Who owns the AWAITING_INPUT transition: the input_type slot, and ONLY it.

Buttons are not evidence that a turn is paused. Several `actions` payloads ride
events where the graph has already ended — the post-turn "Retry failed tasks"
chip (`turn_actions`), the credits-upgrade CTA, the turn-resume prompt, and the
locally replayed batched-choice cards. When the actions slot inferred the state
from the presence of buttons, the retry chip flipped the session into
AWAITING_INPUT; SSE-complete deliberately refuses to reset that state, so the
pill stranded on "Awaiting Input" and the chip's own IDLE-only handler refused
the very click the chip exists to make ("Chat is busy — wait for the current
turn to finish").

Every genuinely paused turn carries its `input_type` in the SAME slot event as
its buttons (backend SlotTransformer, INPUT_REQUIRED case), so nothing is lost
by letting `_apply_input_type_slot` own the transition alone — provided its
allowlist covers every input_type the backend can emit, `confirm` included.
"""

import importlib.util
import logging
import sys
import types
from enum import Enum
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SLOT_PROCESSOR = ROOT / (
    "src/scripts/mixar/modules/space_mixie_chat/core/slot_processor.py"
)

# Every input_type the backend's request_user_input / gate paths can emit.
# Mirrors modules/agent/tools/domains/user_input.py plus the two file pickers.
BACKEND_INPUT_TYPES = (
    "text", "choice", "confirm", "approval", "file_save", "file_open",
)


class SessionState(Enum):
    OFFLINE = "offline"
    CONNECTING = "connecting"
    IDLE = "idle"
    BUSY = "busy"
    MODIFYING = "modifying"
    AWAITING_INPUT = "awaiting_input"


class _FakeSession:
    """Stands in for the SessionManager singleton, recording transitions."""

    def __init__(self):
        self.state = SessionState.BUSY

    def get_state(self, scene):
        return self.state

    def set_state(self, scene, state):
        self.state = state


class _Item:
    def __init__(self):
        self.label = ""
        self.value = ""
        self.style = "DEFAULT"
        self.image = ""
        self.asset_name = ""
        self.library = ""
        self.blend_file = ""
        self.asset_type = ""


class _Collection(list):
    """Minimal stand-in for a Blender CollectionProperty."""

    def add(self):
        item = _Item()
        self.append(item)
        return item

    def clear(self):
        del self[:]


class _Bubble:
    def __init__(self):
        self.action_items = _Collection()
        self.input_type = ""


def _load_processor(session):
    """Load slot_processor.py in isolation — no bpy, no Blender package tree.

    A generator: the caller must consume it for the duration of the test so the
    stub package tree stays installed, then let it finish to restore sys.modules.
    """
    package = types.ModuleType("slot_iso")
    package.__path__ = []
    core = types.ModuleType("slot_iso.core")
    core.__path__ = []

    constants = types.ModuleType("slot_iso.constants")
    constants.SessionState = SessionState
    constants.TEMP_PLACEHOLDER_PREFIX = "temp_placeholder_"

    session_mod = types.ModuleType("slot_iso.core.session")
    session_mod.get_session_manager = lambda: session

    ui_utils = types.ModuleType("slot_iso.core.ui_utils")
    ui_utils.bump_layout_epoch = lambda scene: None

    previews = types.ModuleType("slot_iso.core.asset_choice_previews")
    previews.cleanup_bubble = lambda bubble: None
    previews.schedule = lambda scene, bubble: None

    mixar = types.ModuleType("mixar")
    mixar.__path__ = []
    config = types.ModuleType("mixar.config")
    config.__path__ = []
    logging_config = types.ModuleType("mixar.config.logging_config")
    logging_config.get_logger = logging.getLogger

    injected = {
        "mixar": mixar,
        "mixar.config": config,
        "mixar.config.logging_config": logging_config,
        "slot_iso": package,
        "slot_iso.core": core,
        "slot_iso.constants": constants,
        "slot_iso.core.session": session_mod,
        "slot_iso.core.ui_utils": ui_utils,
        "slot_iso.core.asset_choice_previews": previews,
    }
    # The stubs must stay in sys.modules for the whole test: slot_processor
    # imports asset_choice_previews lazily, inside the actions slot itself.
    saved = {k: sys.modules.get(k) for k in injected}
    sys.modules.update(injected)
    spec = importlib.util.spec_from_file_location(
        "slot_iso.core.slot_processor", SLOT_PROCESSOR
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["slot_iso.core.slot_processor"] = module
    spec.loader.exec_module(module)
    yield module.SlotEventProcessor()
    sys.modules.pop("slot_iso.core.slot_processor", None)
    for key, previous in saved.items():
        if previous is None:
            sys.modules.pop(key, None)
        else:
            sys.modules[key] = previous


@pytest.fixture
def processor():
    session = _FakeSession()
    for proc in _load_processor(session):
        yield proc, session


# --- the actions slot must not touch session state ---------------------------

def test_post_turn_chip_does_not_pause_the_session(processor):
    """The retry chip arrives AFTER the graph reached END. If applying it
    paused the session, SSE-complete would never settle to IDLE and the chip
    could never be clicked."""
    proc, session = processor
    proc._apply_actions_slot(
        _Bubble(),
        [{"label": "Retry failed tasks", "value": "retry_failed_tasks",
          "style": "primary"}],
        scene=object(),
    )
    assert session.state is SessionState.BUSY  # untouched; COMPLETE settles it


def test_choice_buttons_alone_do_not_pause_the_session(processor):
    """Buttons carry no state meaning even when they look like a question —
    the locally replayed batched-choice cards send exactly this shape."""
    proc, session = processor
    proc._apply_actions_slot(
        _Bubble(),
        [{"label": "Cycles", "value": "Cycles"},
         {"label": "EEVEE", "value": "EEVEE"}],
        scene=object(),
    )
    assert session.state is SessionState.BUSY


def test_actions_slot_still_renders_its_buttons(processor):
    """Dropping the state flip must not disturb what the slot actually does."""
    proc, _session = processor
    bubble = _Bubble()
    proc._apply_actions_slot(
        bubble,
        [{"label": "Retry failed tasks", "value": "retry_failed_tasks",
          "style": "primary"}],
        scene=object(),
    )
    assert [(i.label, i.value, i.style) for i in bubble.action_items] == [
        ("Retry failed tasks", "retry_failed_tasks", "PRIMARY")
    ]


# --- the input_type slot is the sole owner -----------------------------------

@pytest.mark.parametrize("input_type", BACKEND_INPUT_TYPES)
def test_every_backend_input_type_pauses_the_session(processor, input_type):
    """A gap here is what motivated the removed buttons-derived fallback:
    'confirm' was missing, so a Yes/No/Cancel prompt decayed to Idle on
    SSE-complete and typed text went to /agent/chat instead of answering."""
    proc, session = processor
    proc._apply_input_type_slot(_Bubble(), input_type, scene=object())
    assert session.state is SessionState.AWAITING_INPUT


def test_unknown_input_type_leaves_state_alone(processor):
    proc, session = processor
    proc._apply_input_type_slot(_Bubble(), "", scene=object())
    assert session.state is SessionState.BUSY


# --- ordering + no regression to the removed fallback ------------------------

def test_input_type_is_applied_before_actions():
    """An interrupt ships both slots in ONE event; the pause must be recorded
    before the buttons land, whatever a handler does."""
    source = SLOT_PROCESSOR.read_text(encoding="utf-8")
    handlers = source[
        source.index("        slot_handlers = ["):
        source.index("        for slot_name, handler in slot_handlers:")
    ]
    assert handlers.index('("input_type"') < handlers.index('("actions"')


def test_actions_slot_never_sets_session_state():
    source = SLOT_PROCESSOR.read_text(encoding="utf-8")
    actions_slot = source[
        source.index("    def _apply_actions_slot("):
        source.index("    def _apply_images_slot(")
    ]
    assert "set_state" not in actions_slot
