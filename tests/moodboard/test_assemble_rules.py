# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Assemble part defaults read from the part's name (DESIGN §2.5)."""

import pytest

from mixar.modules.moodboard.core.assemble_rules import (
    BODY_WORDS,
    KEYWORD_RULES,
    body_word,
    match_rule,
    region_word,
    side_override,
)


@pytest.mark.parametrize(
    ("label", "cls", "slot", "hold", "size", "grip"),
    [
        # Warrior sheet: talwar in the right hand, dhal on the left, scabbard at the hip.
        ("Talwar", 'long', 'HAND_R', 'POINT', 52.0, 0.10),
        ("Dhal", 'flat', 'HAND_L', 'FACE_OUT', 30.0, None),
        ("Scabbard", 'long', 'HIP_L', None, 55.0, None),
        # Knight: sword and kite shield (the shield row is exercised below).
        ("Sword", 'long', 'HAND_R', 'POINT', 52.0, 0.10),
        # Archer: bow and quiver.
        ("Bow", 'long', 'HAND_L', 'UPRIGHT', 72.0, 0.50),
        ("Quiver", 'long', 'BACK', None, 45.0, None),
        # Rogue: knife and goggles.
        ("Knife", 'long', 'HAND_R', 'POINT', 18.0, 0.18),
        ("Goggles", 'compact', 'HEAD_FRONT', None, 95.0, None),
        # Mage: staff and orb.
        ("Staff", 'long', 'HAND_R', 'UPRIGHT', 105.0, 0.45),
        ("Orb", 'compact', 'FLOAT_L', None, 11.0, None),
    ],
)
def test_keyword_defaults_for_the_five_example_sheets(label, cls, slot, hold, size, grip):
    rule = match_rule(label)
    assert rule is not None, label
    assert (rule.cls, rule.slot, rule.hold, rule.size_pct, rule.grip) == (
        cls, slot, hold, size, grip)


def test_greatsword_and_crossbow_match_before_sword_and_bow():
    assert match_rule("Greatsword").size_pct == 72.0
    assert match_rule("two-handed sword").size_pct == 72.0
    assert match_rule("Crossbow").slot == 'HAND_R'
    assert match_rule("Crossbow").hold == 'POINT'
    assert match_rule("Longbow").size_pct == 100.0
    assert match_rule("Tower shield").size_pct == 80.0
    assert match_rule("Round shield").size_pct == 48.0
    # First-row-wins: every longer phrase precedes the shorter word it contains.
    order = [keyword for rule in KEYWORD_RULES for keyword in rule.keywords]
    assert order.index("greatsword") < order.index("sword")
    assert order.index("crossbow") < order.index("bow")
    assert order.index("tower shield") < order.index("shield")


def test_whole_word_matching():
    assert match_rule("Elbow pad") is None
    assert match_rule("Swordfish") is None
    assert match_rule("Axes").keywords == ("axe", "hatchet")
    assert match_rule("ornate_talwar-v2").keywords[1] == "talwar"
    assert match_rule("Left-hand item") is None
    assert match_rule("Right-hand item") is None


def test_label_side_words_override():
    assert side_override("Right-hand item") == {'slot': 'HAND_R', 'side': 'R', 'swap_hands': False}
    assert side_override("Left hand item")['slot'] == 'HAND_L'
    assert side_override("left dagger") == {'slot': '', 'side': 'L', 'swap_hands': False}
    assert side_override("Back quiver")['slot'] == 'BACK'
    assert side_override("belt pouch")['slot'] == 'HIP_L'
    assert side_override("Right hip flask") == {'slot': 'HIP_L', 'side': 'R', 'swap_hands': False}
    assert side_override("head jewel")['slot'] == 'HEAD_FRONT'
    assert side_override("Talwar") == {'slot': '', 'side': '', 'swap_hands': False}


def test_left_handed_swaps_hands():
    words = side_override("Left-handed sword")
    assert words == {'slot': '', 'side': '', 'swap_hands': True}
    assert side_override("left handed")['swap_hands'] is True


def test_body_words_warn():
    assert body_word("Turban") == "turban"
    assert body_word("Leather belt pouch") == "belt"
    assert body_word("Gauntlets") == "gauntlet"
    assert body_word("Talwar") is None
    assert body_word("Hornbill feather") is None
    assert {"helmet", "cloak", "tail", "necklace"} <= BODY_WORDS


@pytest.mark.parametrize("label, region", [
    ("Head", "head"), ("Kael head", "head"), ("Left hand", "hand"), ("Hands", "hands"),
    ("Torso", "torso"), ("Upper body", "upper body"), ("Right forearm", "forearm"),
    ("Legs", "legs"), ("Body", "body"),
])
def test_body_regions_are_recognised(label, region):
    assert region_word(label) == region


@pytest.mark.parametrize("label", [
    "Right-hand item", "Left-hand item", "Hand axe", "Head goggles", "Talwar",
    "Head ornament", "Helmet", "Chest armour",
])
def test_items_and_worn_pieces_are_not_regions(label):
    assert region_word(label) is None


def test_region_note_explains_the_skip_and_items_get_none():
    from mixar.modules.moodboard.core.assemble_rules import region_note
    assert "join it into the body mesh" in region_note("Head")
    assert region_note("Right-hand item") == ""
