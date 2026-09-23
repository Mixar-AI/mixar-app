# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""What the Character Sheet to 3D workflow writes onto its cards.

Pure data. Every prompt is ONE paragraph with no newline: Enter in a card's
prompt field runs the card, so a multi-line default could never be edited in
place. Each prompt opens with its subject, because the card label ("Body",
"Right-hand item", …) is also the name the result image and its mesh get.
"""

# The part prompts share one tail: what makes a clean single-object reference.
# "no hand, no figure" and never the literal "no people" (the backend's
# generation routing pins that wording for isolated props).
PART_TAIL = (
    "A single object only, complete and unobstructed: no hand, no figure, no stand, "
    "no second copy, no text, labels or inset views. Same shape, proportions, materials, "
    "colours, engravings and wear as on the sheet; sharpen detail faithfully but never "
    "redesign. Orthographic, centred, whole object in frame with a margin, pure white "
    "background, flat even lighting, no shadow or reflection."
)

BODY_PROMPT = (
    "Body — the same character as the reference sheet, as one clean 3D-reconstruction "
    "reference. Keep the face, age, build, proportions and limb lengths, hairstyle, skin "
    "tone, every clothing layer, pattern, colour and worn accessory exactly as on the sheet. "
    "Remove every item the character holds or carries separately (weapons, shields, staffs, "
    "bows, quivers, bags, orbs, tools) but keep the belts and straps they hang from, and "
    "show the hands, forearms, hips and back they covered complete. Pose: symmetric A-pose, "
    "standing straight, feet shoulder-width apart, toes forward; arms straight and 30 "
    "degrees away from the torso with a clear gap; palms facing down; hands open, fingers "
    "straight and slightly apart. Change only the pose, never the proportions. Neutral "
    "expression, mouth closed, eyes open. Straight-on front orthographic view, whole figure "
    "from the top of the head or headwear to the soles with a margin, centred. Pure white "
    "background, flat even lighting, no shadows, no floor, no text, labels, colour swatches "
    "or inset panels. One figure only."
)

RIGHT_PROMPT = (
    "Right-hand item — the weapon or tool the character holds in the right hand on the "
    "reference sheet, shown alone as one isolated object: upright and vertical, grip or "
    "handle at the BOTTOM, tip or head at the TOP, the flat side facing the camera, cutting "
    "edge (if any) on the LEFT of the image, no sheath. " + PART_TAIL
)

LEFT_PROMPT = (
    "Left-hand item — the shield, bow or other item the character holds in the left hand "
    "on the reference sheet, shown alone as one isolated object: a shield seen straight-on "
    "from the front with its decorated face toward the camera and top edge up; a long item "
    "upright with its grip at the BOTTOM. " + PART_TAIL
)

# (lane key, card label, prompt). The body lane is first: it sits on top, and
# its 3D card (or its rig) feeds Assemble's body input.
LANES = (
    ('body', "Body", BODY_PROMPT),
    ('right', "Right-hand item", RIGHT_PROMPT),
    ('left', "Left-hand item", LEFT_PROMPT),
)

# Assemble rows the builder writes explicitly: parts:0 is the right lane,
# parts:1 the left one. Everything else stays Auto.
DEFAULT_ROWS = {0: {'slot': 'HAND_R'}, 1: {'slot': 'HAND_L'}}

RIG_LABEL = "Rig Body"
ASSEMBLE_LABEL = "Assemble"

# The frame is named after the sheet ("<sheet> to 3D"), or this without one.
FRAME_STEM = "Character Sheet to 3D"
FRAME_SUFFIX = " to 3D"
# Sheet names are cut to this many UTF-8 BYTES: the frame name's maxlen counts
# bytes, and "<sheet> to 3D" plus a " N" uniqueness suffix must fit whole.
FRAME_SHEET_NAME_BYTES = 60

NOTE_FONT = 40
NOTE_WIDTH = 1600.0

NOTE_TEXT = (
    "How to use: 1) Generate the three reference cards and compare each with your sheet; "
    "edit a prompt and regenerate if it drifted. For small props, crop the prop's panel "
    "(Crop tool) and connect it to that card first. 2) Generate each 3D card. 3) Generate "
    "Rig Body. 4) Press Assemble: parts attach to the rig's hand bones — change slot and "
    "size in Assemble's Settings. Rename a part card (F2) to your item's name and describe "
    "it in its prompt. Add a part: Shift+D its reference and 3D cards, then connect the new "
    "3D card to Assemble. One-piece character: delete the part lanes and change the Body "
    "prompt to keep the items stowed with empty hands. Texture or retopologize the body "
    "BEFORE Rig Body — both return an unrigged copy. Generating every card runs {jobs} "
    "jobs; Assemble is local and free."
)

# Conditional prefixes, prepended in this order. Kept short: with both, the
# note must still fit a text box (``text`` maxlen 1024, so 1023 UTF-8 bytes).
NO_SHEET_LINE = "First connect your character sheet to the three reference cards. "
NO_RIG_LINE = (
    "Auto Rig is unavailable: Assemble places parts without bones. Later, add Auto Rig "
    "from Body's 3D card, wire it to Assemble's Body input and press Assemble again. "
)
NOTE_MAX_BYTES = 1023

NOTICE = "Generate the three reference cards first, then compare them with the sheet"


def note_text(*, has_sheet: bool, has_rig: bool) -> str:
    """The note: how-to plus what this particular build is missing."""
    jobs = 2 * len(LANES) + (1 if has_rig else 0)
    prefix = ("" if has_sheet else NO_SHEET_LINE) + ("" if has_rig else NO_RIG_LINE)
    return prefix + NOTE_TEXT.format(jobs=jobs)
