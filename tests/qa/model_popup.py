# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Drive the island's model chip and the model card it opens.

The card is drawn by hand over the island window (agent_ui_model_card*.cc),
so it has no Blender widgets: it exports QA targets instead —
`model_card` (text = open tab id), `model_card_tab` (value = tab id, sel =
open), `model_card_row` (detail = pick | level, value = model, sel =
current), `model_card_disclosure`, `model_card_note`, `model_card_footer`
and `model_card_scrollbar`. Only rows scrolled into view are exported.
"""

import time

CHIP = {'op': 'MIXAR_OT_agent_model_card', 'area_type': 'AGENT_BUBBLE'}
CARD = {'surface': 'model_card'}
TAB = {'surface': 'model_card_tab'}
PICK = {'surface': 'model_card_row'}
SETTINGS_ROW = {'surface': 'model_card_footer'}
THINKING = {'surface': 'model_card_disclosure'}
WM = 'bpy.context.window_manager'
OPEN = f"bool(drv.find(**{CARD!r}))"


def chip(qa):
    """(source, badge, name, state) as the chip draws them."""
    return tuple(qa.eval(f"wm={WM}\nresult=[wm.mixar_agent_source, wm.mixar_agent_source_label, "
                         "wm.mixar_agent_chip_name, wm.mixar_agent_source_state]"))


def is_open(qa):
    return bool(qa.eval(f"result={OPEN}"))


def open_popup(qa):
    """Click the chip until the card is up. The first native click after the
    island reopens can commit its composer focus instead: retry once, only
    when the card demonstrably stayed shut. A card already up is closed
    first, so every open starts on the source in use, scrolled to the pick."""
    close_popup(qa)
    for _ in range(2):
        qa.click(**CHIP)
        time.sleep(.5)
        if is_open(qa):
            return
    qa.wait(OPEN, timeout=5)


def press_on_card(qa, key):
    """A key press delivered to the island window the card is on."""
    qa.eval(f"card=drv.find_one(**{CARD!r})\ndrv.press(card['_win'], {key!r})\nresult=True")


def close_popup(qa):
    if is_open(qa):
        press_on_card(qa, 'ESC')
        qa.wait(f"not {OPEN}", timeout=5)


def open_tab(qa):
    """The tab the card shows ('MIXIE' | 'KEY' | 'LOCAL')."""
    return qa.eval(f"result=next((w['value'] for w in drv.find(**{TAB!r}) if w.get('sel')), '')")


def show_tab(qa, tab_id):
    if not is_open(qa):
        open_popup(qa)
    if open_tab(qa) == tab_id:
        return
    qa.click(**TAB, value=tab_id)
    qa.wait(f"next((w['value'] for w in drv.find(**{TAB!r}) if w.get('sel')), '') == {tab_id!r}",
            timeout=5)


def rows(qa):
    """[(label, enabled)] of the picks (and unfolded levels) in view."""
    return [(w['text'], w['enabled']) for w in qa.find(**PICK)['widgets']]


def pick(qa, text, contains=False):
    """Click a pick; the card closes once its operator ran."""
    qa.click(**PICK, text=text, contains=contains)


def settings(qa, text=None):
    """Click a footer action (AI Provider Settings)."""
    qa.click(**dict(SETTINGS_ROW, **({'text': text} if text else {})))


def open_settings(qa):
    """AI Provider Settings from the card, the way a person gets there: with
    no key saved the key tab is itself the action (one click); otherwise its
    footer ("Manage key…" / "Enter key…")."""
    open_popup(qa)
    action = qa.eval(f"result=next((w.get('detail', '') for w in drv.find(**{TAB!r}) if w['value'] == 'KEY'), '')")
    if action == 'settings':
        qa.click(**TAB, value='KEY')
        return
    show_tab(qa, 'KEY')
    settings(qa)
