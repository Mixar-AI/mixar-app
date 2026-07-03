# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Development mode dummy data for Mixie Chat.

Provides mock data for UI development without requiring a backend connection.
"""

import random
from typing import Optional

from mixar.config.logging_config import get_logger

from ..constants import SessionState

logger = get_logger(__name__)


# ============================================================================
# DUMMY RESPONSES FOR MESSAGE SIMULATION
# ============================================================================

DUMMY_RESPONSES = [
    "I'll help you with that! Let me analyze your request and create a plan.",
    "Got it! I'm processing your request now.",
    "Understood. I'll create the necessary objects and materials for you.",
    "I'll work on that right away. Let me set things up.",
    "Sure thing! I'll handle that for you.",
    "Let me take care of that. I'll start working on it now.",
]

# Keyword-based responses for more realistic simulation
KEYWORD_RESPONSES = {
    "cube": "I'll create a cube for you with the specified properties. Let me set up the geometry and apply any materials you've requested.",
    "sphere": "I'll add a sphere to your scene. I'll configure the segments and radius, then apply any materials specified.",
    "material": "I'll create a new material with the properties you've described. Let me set up the shader nodes appropriately.",
    "color": "I'll adjust the color settings for you. Let me update the material properties.",
    "delete": "I'll remove the specified objects from your scene. Let me handle that cleanup.",
    "move": "I'll reposition the objects as requested. Let me update their transforms.",
    "scale": "I'll resize the objects to your specifications. Let me adjust their scale values.",
    "rotate": "I'll rotate the objects as specified. Let me update their rotation values.",
    "light": "I'll add lighting to your scene. Let me set up the light type, intensity, and color.",
    "camera": "I'll configure the camera for you. Let me adjust the position and settings.",
    "render": "I'll help you with rendering. Let me check the render settings and prepare the output.",
    "texture": "I'll apply texturing to your objects. Let me set up the UV mapping and texture nodes.",
    "animation": "I'll set up the animation for you. Let me create the keyframes and configure the timeline.",
    "help": "I'm here to help! I can create objects, apply materials, set up lighting, and much more. Just describe what you'd like to do.",
}


def get_dummy_response(user_message: str) -> str:
    """
    Get a contextual dummy response based on the user's message.

    Args:
        user_message: The user's input message

    Returns:
        A simulated agent response string
    """
    lower_message = user_message.lower()

    # Check for keyword matches
    for keyword, response in KEYWORD_RESPONSES.items():
        if keyword in lower_message:
            return response

    # Fallback to random generic response
    return random.choice(DUMMY_RESPONSES)


# Sample chat messages for testing different states
DUMMY_MESSAGES = [
    {
        "sender": "USER",
        "text": "Create a simple cube with a red material"
    },
    {
        "sender": "AGENT",
        "text": "I'll create a cube and apply a red material to it. Let me break this down into steps."
    },
    {
        "sender": "USER",
        "text": "Now add a sphere next to it with a blue metallic material"
    },
    {
        "sender": "AGENT",
        "text": "I'll add a sphere positioned next to the cube and create a blue metallic material for it."
    },
]

# Sample plan for approval state
DUMMY_PLAN = {
    "summary": "Create a UV sphere with a metallic blue material and position it next to the existing cube.",
    "steps": [
        {
            "index": 0,
            "description": "Add a UV sphere with 32 segments",
            "status": "completed"
        },
        {
            "index": 1,
            "description": "Position sphere at X=3, Y=0, Z=1",
            "status": "completed"
        },
        {
            "index": 2,
            "description": "Create new material 'Blue Metallic'",
            "status": "in_progress"
        },
        {
            "index": 3,
            "description": "Set material color to blue (0.1, 0.3, 0.8)",
            "status": "pending"
        },
        {
            "index": 4,
            "description": "Set metallic value to 0.9 and roughness to 0.2",
            "status": "pending"
        },
        {
            "index": 5,
            "description": "Apply material to sphere",
            "status": "pending"
        },
    ],
    "requires_approval": True,
}

# Sample streaming content (thinking text)
DUMMY_STREAMING_CONTENT = """Analyzing the request...

The user wants to create a sphere with a blue metallic material. I need to:
1. First check if there's an existing cube in the scene
2. Calculate the appropriate position for the new sphere
3. Create the sphere with proper UV mapping
4. Set up a principled BSDF material with metallic properties

Let me start by examining the current scene state..."""

# Sample error for retry state
DUMMY_ERROR = "Failed to create material: Node tree already exists with name 'Blue Metallic'"

# Interrupt data for testing
DUMMY_INTERRUPT = {
    "type": "plan_approval",
    "message": "Please review the plan before I execute it.",
    "actions": ["approve", "modify", "abort"],
}


class DevDataProvider:
    """
    Provides dummy data for different session states.

    Use this class to populate the UI with test data during development.
    """

    _current_state_index: int = 0

    # States to cycle through for testing
    STATES_CYCLE = [
        SessionState.IDLE,
    ]

    @classmethod
    def get_dummy_messages(cls) -> list[dict]:
        """Get the list of dummy chat messages."""
        return DUMMY_MESSAGES.copy()

    @classmethod
    def get_dummy_plan(cls) -> dict:
        """Get dummy plan data."""
        return DUMMY_PLAN.copy()

    @classmethod
    def get_streaming_content(cls) -> str:
        """Get dummy streaming/thinking content."""
        return DUMMY_STREAMING_CONTENT

    @classmethod
    def get_error_message(cls) -> str:
        """Get dummy error message."""
        return DUMMY_ERROR

    @classmethod
    def get_interrupt_data(cls) -> dict:
        """Get dummy interrupt data."""
        return DUMMY_INTERRUPT.copy()

    @classmethod
    def get_next_state(cls) -> SessionState:
        """Cycle through states for testing."""
        state = cls.STATES_CYCLE[cls._current_state_index]
        cls._current_state_index = (cls._current_state_index + 1) % len(cls.STATES_CYCLE)
        return state

    @classmethod
    def reset_state_cycle(cls) -> None:
        """Reset state cycle to beginning."""
        cls._current_state_index = 0


def populate_dev_session(session, scene, initial_state: Optional[SessionState] = None):
    """
    Populate session and scene with dummy data for development.

    Args:
        session: SessionManager instance
        scene: Blender scene to populate with messages
        initial_state: Optional state to set, defaults to IDLE
    """
    # Clear existing messages
    scene.mixie_chat_messages.clear()

    # Add dummy messages
    for msg_data in DUMMY_MESSAGES:
        msg = scene.mixie_chat_messages.add()
        msg.sender = msg_data["sender"]
        msg.text = msg_data["text"]

    # Set state
    state = initial_state or SessionState.IDLE
    session.set_state(scene, state)

    # Populate state-specific data
    if state == SessionState.OFFLINE:
        session.set_error(scene)

    logger.debug(f"Populated with dummy data, state: {state.value}")
