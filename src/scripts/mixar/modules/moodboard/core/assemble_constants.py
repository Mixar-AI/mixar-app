# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Shared identity of the local Assemble Character node.

The schema (sockets and per-part settings rows), the engine and the Character
Sheet to 3D template builder all key on these names, so they live in one
bpy-free place.
"""

BODY_SOCKET = "body"
PART_SOCKET_COUNT = 8
PART_GROUP = "parts"


def part_socket(index: int) -> str:
    return f"{PART_GROUP}:{index}"


PARAM_KINDS = ("slot", "hold", "size", "flip")


def param_name(kind: str, index: int) -> str:
    return f"{kind}:{index}"


SLOT_CHOICES = (
    ("AUTO", "Auto (from name)"),
    ("HAND_R", "Right hand"),
    ("HAND_L", "Left hand"),
    ("FOREARM_R", "Right forearm"),
    ("FOREARM_L", "Left forearm"),
    ("BACK", "Back"),
    ("HIP_R", "Right hip"),
    ("HIP_L", "Left hip"),
    ("HEAD_FRONT", "Head front"),
    ("HEAD_TOP", "Head top"),
    ("FLOAT_R", "Float by right hand"),
    ("FLOAT_L", "Float by left hand"),
)
HOLD_CHOICES = (
    ("AUTO", "Auto"),
    ("POINT", "Point forward"),
    ("UPRIGHT", "Upright"),
    ("FACE_OUT", "Face outward"),
    ("AS_IS", "As generated"),
)
HAND_SLOTS = frozenset({"HAND_R", "HAND_L"})
FOREARM_SLOTS = frozenset({"FOREARM_R", "FOREARM_L"})
HEAD_SLOTS = frozenset({"HEAD_FRONT", "HEAD_TOP"})
FLOAT_SLOTS = frozenset({"FLOAT_R", "FLOAT_L"})
# Longest dimension as a percentage of the body height (head slots: of head
# width). 0 means "auto": the part's name picks a default size.
SIZE_MIN, SIZE_MAX = 0.0, 250.0
