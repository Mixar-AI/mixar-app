#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Hosted agent model picker: both surfaces, the menu matrix, BYOK, fail-closed.

Spends no credits and needs no backend. The catalog projection and the menu row
builder are driven with synthetic payloads (the way `byok_http_e2e.py` drives
cached state), so the scenario proves the CLIENT contract — what the user sees
and clicks — without a live `/agent/models`.

Eight checks:

1. The six `mixar_agent_model_*` WindowManager mirror keys exist, and `clear()`
   (the logout path) empties every one of them.
2. An EMPTY catalog fails closed to a disabled sentinel — never a hardcoded
   model list — with the key route still offered beside it.
3. The menu matrix: a FLAT `Provider · Model` list in SERVER order, the radio
   on the active pick, an ineligible row GREYED (`enabled=False`) rather than
   hidden, and the tail `Reset to default` then the key route. Thinking levels
   are a SUBMENU of the current pick, never inline rows — inline made a 26-row
   menu that Blender column-wrapped and the island clipped.
4. BYOK active prefixes the override note and greys every row EXCEPT the key
   route, which must stay clickable.
5. Both surfaces draw one control each, from ONE mirror: the Mixie Chat footer
   dropdown (`mixie_chat_footer_region_draw`) and the island chip
   (`agent_island`). A pick changes both.
6. BYOK leaves both BUTTONS enabled (their menu holds the only route to the
   BYOK dialog) and the footer's tooltip explains why the pick is overridden.
7. Vision: the island chip and the footer dropdown, picked and BYOK-overridden.
8. A REAL click on the key row opens the AI Provider Settings dialog (a
   Menu's EXEC operator context once made it run a no-op execute()) — and
   opens it in the MAIN window, not the ~460px island it was clicked in.

The footer picker is deliberately absent inside the Agent Bubble (`is_bubble`) —
the island chip is that window's control — so check 5 opens a real MIXIE_CHAT
editor rather than relying on the bubble.

QA_HARNESS=/path/to/mixar-qa-harness QA_SCENARIO_OUT=/tmp/model-picker-qa \
    python3 tests/qa/agent_model_picker_e2e.py
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA, ScenarioFail, run_scenario  # noqa: E402

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/model-picker-qa'))
OUT.mkdir(parents=True, exist_ok=True)

# The QA dump spells operators as bl_idname (WM_OT_call_menu), NOT the
# `wm.call_menu` form the C++ passes to uiDefButO. Querying the dotted form
# silently returns zero widgets and reads as "the button is missing".
PICKER_OP = 'WM_OT_call_menu'

MIRROR_FIELDS = (
    'mixar_agent_model_provider',
    'mixar_agent_model_id',
    'mixar_agent_model_label',
    'mixar_agent_model_thinking',
    'mixar_agent_model_byok_active',
    'mixar_agent_model_eligible',
)

READ_MIRROR = """
from mixar.modules.byok.core import preference_state
result = preference_state.snapshot()
"""

ROW_MATRIX = """
from mixar.modules.byok.core import model_menu as M
def shape(rows):
    return [[r.kind, r.label, r.enabled, r.active] for r in rows]
models = [
  {'provider_id':'anthropic','provider_label':'Anthropic','model_id':'claude-sonnet-4-6',
   'model_label':'Claude Sonnet 4.6','eligible':True,
   'thinking_levels':['low','medium','high','max']},
  {'provider_id':'openai','provider_label':'OpenAI','model_id':'gpt-5',
   'model_label':'GPT-5','eligible':False,'thinking_levels':[]},
]
result = {
 'empty': shape(M.build_rows([])),
 'populated': shape(M.build_rows(models, active_provider='anthropic',
                                active_model='claude-sonnet-4-6', active_thinking='high')),
 'byok': shape(M.build_rows(models, byok_active=True)),
 'submenu': shape(M.build_thinking_rows(models, active_provider='anthropic',
                                        active_model='claude-sonnet-4-6',
                                        active_thinking='high')),
}
"""

PICKERS = f"""
import bpy, json
wm = bpy.data.window_managers[0]
data = json.loads(wm.mixar_qa_ui_dump)
result = {{
  'byok': wm.mixar_agent_model_byok_active,
  'label': wm.mixar_agent_model_label,
  'buttons': [{{'block': w.get('block'), 'text': w.get('text'),
               'enabled': w.get('enabled'), 'tip': (w.get('tip') or '')}}
              for w in data['widgets'] if w.get('op') == {PICKER_OP!r}],
}}
"""

OPEN_CHAT_EDITOR = """
import bpy
target = None
for win in bpy.context.window_manager.windows:
    for area in win.screen.areas:
        if area.type == 'VIEW_3D':
            target = area
            break
    if target:
        break
if target:
    target.type = 'MIXIE_CHAT'
result = {'opened': bool(target)}
"""


def _apply(values):
    return ("from mixar.modules.byok.core import preference_state as P\n"
            f"P.apply_local({values!r})\n"
            "result = P.snapshot()\n")


def settle(qa, seconds=3.0):
    """Let a tagged redraw actually reach the framebuffer before snapping.

    `tag_redraw` only queues; an idle Blender pumps on its next loop. Snapping
    too early photographs a STALE frame — which once read as "the disabled
    state looks identical to the enabled one" when the pixels simply had not
    been redrawn yet. Never shorten this without re-proving a real diff.
    """
    time.sleep(seconds)


#: The FOOTER's tooltip is what this scenario asserts on, not the island's.
#: `mixar_qa_ui_dump` walks the region's uiBlocks, and the island's TOOLS
#: region can still be holding the previous frame's block when the dump is
#: read — its button then reports a tooltip the app is no longer drawing.
#: Confirmed not to be a product bug: the island PAINTER and the button are
#: built from one `AgentIslandState`, and the chip visibly dims the moment
#: BYOK goes active, so the state the button was built from was correct.
#: Asserting the island's tooltip text here would pin a harness artefact.
FOOTER_TOOLTIP_UPDATED = (
    "any('API key' in (w.get('tip') or '')"
    " for w in __import__('json').loads("
    "   __import__('bpy').data.window_managers[0].mixar_qa_ui_dump)['widgets']"
    " if w.get('op') == 'WM_OT_call_menu'"
    " and w.get('block') == 'mixie_chat_footer_region_draw')"
)


def run(qa):
    qa.step('dismiss_splash', qa.dismiss_splash)
    qa.step('open_chat', qa.open_chat)

    # --- 1. the mirror exists, and clearing it empties it -----------------
    # Deliberately NOT "is empty at boot": that only holds on a fresh
    # instance, and the ship loop keeps ONE app up across iterations. The
    # re-runnable invariant is that `clear()` — the logout path — empties
    # every field, which is also what stops one account's pick leaking into
    # the next.
    mirror = qa.step('read_mirror', qa.eval, READ_MIRROR)
    missing = [f for f in MIRROR_FIELDS if f not in mirror]
    if missing:
        raise ScenarioFail(f"the WM mirror is missing keys the C++ reads: {missing}")

    cleared = qa.step('clear_mirror', qa.eval,
                      "from mixar.modules.byok.core import preference_state as P\n"
                      "P.clear()\n"
                      "result = P.snapshot()\n")
    leftovers = {f: cleared[f] for f in
                 ('mixar_agent_model_provider', 'mixar_agent_model_id',
                  'mixar_agent_model_label', 'mixar_agent_model_thinking')
                 if cleared[f]}
    if leftovers or cleared['mixar_agent_model_byok_active']:
        raise ScenarioFail(f"clear() left a previous pick behind: {leftovers or cleared}")

    # --- 2/3/4. the menu matrix -------------------------------------------
    rows = qa.step('menu_row_matrix', qa.eval, ROW_MATRIX)

    empty = rows['empty']
    # Fails closed to a disabled sentinel — never a hardcoded model list. The
    # key row rides along so an empty catalog is not a dead end.
    if [r[0] for r in empty] != ['SENTINEL', 'BYOK'] or empty[0][2]:
        raise ScenarioFail(
            f"an empty catalog must fail closed to a disabled sentinel plus the "
            f"key route, got {empty}")

    populated = rows['populated']
    kinds = [r[0] for r in populated]
    # Flat model list; levels live in a submenu, so the parent stays short
    # enough that Blender never column-wraps it.
    if kinds != ['MODEL', 'MODEL', 'THINKING_MENU', 'RESET', 'BYOK']:
        raise ScenarioFail(f"unexpected row shape/order: {kinds}")
    if populated[0][1] != 'Anthropic · Claude Sonnet 4.6':
        raise ScenarioFail(f"rows must read 'Provider · Model', got {populated[0][1]!r}")
    active = [r[1] for r in populated if r[3]]
    if active != ['Anthropic \u00b7 Claude Sonnet 4.6']:
        raise ScenarioFail(f"the radio must sit on the active pick alone, got {active}")
    submenu = [r for r in rows['submenu']]
    if [r[1] for r in submenu] != ['Thinking: Low', 'Thinking: Medium',
                                   'Thinking: High', 'Thinking: Max']:
        raise ScenarioFail(f"the thinking submenu must list the pick's levels: {submenu}")
    if [r[3] for r in submenu] != [False, False, True, False]:
        raise ScenarioFail(f"the submenu must mark the stored level: {submenu}")
    ineligible = [r for r in populated if r[1] == 'OpenAI · GPT-5']
    if not ineligible or ineligible[0][2]:
        raise ScenarioFail("an ineligible model must be GREYED, not hidden")
    if [r[0] for r in populated[-2:]] != ['RESET', 'BYOK']:
        raise ScenarioFail(
            f"the menu must close with Reset then the key route, got "
            f"{[r[0] for r in populated[-2:]]}")

    byok_rows = rows['byok']
    if byok_rows[0][0] != 'NOTE':
        raise ScenarioFail("BYOK must lead with the override note")
    if any(r[2] for r in byok_rows if r[0] == 'MODEL'):
        raise ScenarioFail("BYOK must disable every model row")

    # The escape hatch. PR #1562 removed the AI Provider Settings entry from
    # the account card AND the topbar fallback menu, so this row is the only
    # route to it. A user with a key configured has every row above greyed BY
    # that key — if this one is missing or disabled they are simply stuck.
    for state_name, state_rows in (('populated', populated), ('byok', byok_rows),
                                   ('empty', empty)):
        keys = [r for r in state_rows if r[0] == 'BYOK']
        if len(keys) != 1:
            raise ScenarioFail(
                f"{state_name}: expected exactly one key row, got {len(keys)}")
        if not keys[0][2]:
            raise ScenarioFail(
                f"{state_name}: the key row must stay clickable, it is the only "
                "way to clear a key that disables everything else")
    if 'remove' not in [r for r in byok_rows if r[0] == 'BYOK'][0][1].lower():
        raise ScenarioFail("with a key in use the row must offer to REMOVE it")

    # --- 5. both surfaces, one mirror -------------------------------------
    qa.step('open_chat_editor', qa.eval, OPEN_CHAT_EDITOR)
    qa.step('pick_a_model', qa.eval, _apply({
        'mixar_agent_model_provider': 'anthropic',
        'mixar_agent_model_id': 'claude-sonnet-4-6',
        'mixar_agent_model_label': 'Claude Sonnet 4.6',
        'mixar_agent_model_thinking': 'high',
        'mixar_agent_model_byok_active': False,
    }))
    settle(qa)
    picked = qa.step('read_pickers', qa.eval, PICKERS)
    blocks = {b['block'] for b in picked['buttons']}
    for expected in ('mixie_chat_footer_region_draw', 'agent_island'):
        if expected not in blocks:
            raise ScenarioFail(f"no model picker on the {expected} surface: {blocks}")
    if not all(b['enabled'] for b in picked['buttons']):
        raise ScenarioFail(f"the picker must be live without BYOK: {picked['buttons']}")
    footer = next(b for b in picked['buttons']
                  if b['block'] == 'mixie_chat_footer_region_draw')
    if 'Claude Sonnet 4.6' not in (footer['text'] or ''):
        raise ScenarioFail(f"the footer label did not follow the pick: {footer['text']!r}")

    shot_picked = str(OUT / 'model_picker_picked.png')
    qa.step('snap_picked', qa.snap, shot_picked)

    # --- 6. BYOK disables both --------------------------------------------
    qa.step('byok_takes_over', qa.eval, _apply({'mixar_agent_model_byok_active': True}))
    # Bring the footer through a real interaction before inspecting its uiBlock.
    # With the island active, the other native window may retain an old frame.
    qa.step('open_footer_under_byok', qa.click,
            op=PICKER_OP, area_type='MIXIE_CHAT')
    qa.step('dismiss_footer_menu', qa.cmd, 'press', key='ESC')
    qa.step('await_footer_repaint', qa.wait, FOOTER_TOOLTIP_UPDATED, timeout=20)
    settle(qa)
    under_byok = qa.step('read_pickers_byok', qa.eval, PICKERS)
    # The BUTTON stays clickable on purpose — its menu holds the only route to
    # the AI Provider Settings dialog. What BYOK greys is the menu's contents,
    # asserted above. Disabling the button here would lock a BYOK user out of
    # clearing the key that is disabling their picker.
    if not all(b['enabled'] for b in under_byok['buttons']):
        raise ScenarioFail(
            f"BYOK must not disable the button itself: {under_byok['buttons']}")
    footer_tip = next(b['tip'] for b in under_byok['buttons']
                      if b['block'] == 'mixie_chat_footer_region_draw')
    if 'API key' not in (footer_tip or ''):
        raise ScenarioFail(f"the picker must say WHY it is overridden: {footer_tip!r}")
    # The island's tooltip is deliberately NOT asserted — see
    # FOOTER_TOOLTIP_UPDATED. What matters there, and IS asserted above, is
    # that its button stays enabled so the key route remains reachable.

    # --- 7. vision --------------------------------------------------------
    shot_byok = str(OUT / 'model_picker_byok_disabled.png')
    qa.step('snap_byok', qa.snap, shot_byok)

    qa.step('restore_no_byok', qa.eval, _apply({'mixar_agent_model_byok_active': False}))

    # --- 8. the key row OPENS the dialog — through a real click ------------
    # The row existing and being enabled was asserted above, and it was
    # still broken: a Menu layout runs operators in an EXEC context, the
    # dialog operator works in invoke() only, so the click ran a no-op
    # execute() and opened nothing. Only a real click on the real row
    # catches that class of bug — the operator invoked directly works fine.
    qa.step('expand_island_for_key_row', qa.open_chat)
    qa.step('click_key_row', qa.cmd, 'choose',
            widget={'op': PICKER_OP, 'area_type': 'AGENT_BUBBLE'},
            item='API key', contains=True)
    qa.step('await_dialog', qa.wait,
            "any(w.get('popup') and 'AI Provider Settings' in (w.get('text') or '')"
            " for w in __import__('json').loads("
            "   __import__('bpy').data.window_managers[0].mixar_qa_ui_dump)['widgets'])",
            timeout=10)
    # ...and in the MAIN window, not the island it was clicked from. The
    # island is ~460px tall; a dialog opened there is a clipped sliver.
    where = qa.step('dialog_window_kind', qa.eval,
                    "import bpy, json\n"
                    "wm = bpy.data.window_managers[0]\n"
                    "ws = json.loads(wm.mixar_qa_ui_dump)['widgets']\n"
                    "by_ptr = {w.as_pointer(): [a.type for a in w.screen.areas]"
                    " for w in wm.windows}\n"
                    "result = sorted({str(by_ptr.get(w['w'])) for w in ws"
                    " if w.get('popup') and 'AI Provider Settings' in (w.get('text') or '')})\n")
    if any('AGENT_BUBBLE' in k for k in where) or not where:
        raise ScenarioFail(f"the dialog must open in the main window, not the island: {where}")
    settle(qa, 1.0)
    shot_dialog = str(OUT / 'model_picker_key_row_opens_dialog.png')
    qa.step('snap_dialog', qa.snap, shot_dialog)
    # Resolve the dialog's actual window so ESC cannot hit another surface.
    dialog_win = qa.step('find_dialog_window', qa.eval,
                         "import bpy, json\n"
                         "ws = json.loads(bpy.data.window_managers[0].mixar_qa_ui_dump)['widgets']\n"
                         "result = next(w['w'] for w in ws if w.get('popup')"
                         " and 'AI Provider Settings' in (w.get('text') or ''))\n")
    qa.step('dismiss_dialog', qa.cmd, 'press', key='ESC', window=dialog_win)
    qa.step('await_dialog_closed', qa.wait,
            "not any(w.get('popup') and 'AI Provider Settings' in (w.get('text') or '')"
            " for w in __import__('json').loads("
            "   __import__('bpy').data.window_managers[0].mixar_qa_ui_dump)['widgets'])",
            timeout=10)

    return {
        'mirror_fields': list(MIRROR_FIELDS),
        'empty_catalog_fails_closed': True,
        'row_kinds': kinds,
        'ineligible_greyed_not_hidden': True,
        'byok_disables_every_row': True,
        'surfaces': sorted(blocks),
        'byok_greys_rows_but_keeps_the_button_open': True,
        'key_route_reachable_in_every_state': True,
        'snaps': [shot_picked, shot_byok],
    }


if __name__ == '__main__':
    run_scenario('agent_model_picker_e2e', run)
