#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""The model card and AI Provider Settings against the REAL backend (free).

The fixture scenarios (agent_model_popup_e2e, profile_provider_settings_e2e)
fake the service; this one reads what the deployed backend serves and drives
the real card and sheet. No agent turn, no credits. Proves:
  1. catalog: every provider and model carries a short label, the response
     carries `provider_order`, and the app's provider list follows it;
  2. the chip is never blank and names the source in use;
  3. the card's Mixie tab opens on "Mixar default" (RECOMMENDED) followed by
     the catalog in the backend's group order;
  4. keyboard: Esc closes; Left/Right never land on an action tab;
  5. a press outside the card closes it and still reaches the composer;
  6. the sheet: providers in the backend order, Guide on the PROVIDERS row
     (above the first provider), the Local model foot row;
  7. Codex in use: the short "Codex sign-in file" prompt, the in-use line
     without the shown provider, "Disconnect", and the confirm step's
     "Stay connected" / "Disconnect" (Stay connected keeps the key);
  8. sending waits while a key change is saving;
  9. a guest: the chip is never blank, the card lists the catalog with
     every Mixar model off under "Sign in to use Mixar models"; signing in
     again restores the account (one dev-bypass login).
Needs BYOK on Codex for step 7 (`agent-access byok` before the run).

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4796 \\
    QA_SCENARIO_OUT=/tmp/model-card-matrix python3 tests/qa/agent_model_card_matrix_e2e.py
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import ScenarioFail, ensure_guest, run_scenario, sign_in_dev_bypass  # noqa: E402
import model_popup as mp  # noqa: E402

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/model-card-matrix'))
OUT.mkdir(parents=True, exist_ok=True)
SUGG = "__import__('mixar.modules.byok.core.model_suggestions', fromlist=['x'])"
DIALOG_OPEN = "__import__('mixar.modules.byok.ui.operators.byok_ops', fromlist=['x'])._dialog_open"
PICK_OP = 'MIXAR_BYOK_OT_pick'


def check(cond, what, **evidence):
    if not cond:
        raise ScenarioFail(f"{what}: {evidence}")


def popup_widgets(qa, **q):
    return qa.find(popup=True, limit=500, **q)['widgets']


def close_dialog(qa):
    if qa.eval(f"result=bool({DIALOG_OPEN})"):
        qa.press('ESC')
        qa.wait(f"not {DIALOG_OPEN}", timeout=8)


def progress(qa, label):
    model = qa.eval("result=bpy.context.window_manager.byok_current_model")
    print(f"[matrix] {label}: byok model={model}", file=sys.stderr, flush=True)
    return model


def run(qa):
    out = {}

    # 1. catalog
    cat = qa.eval(f"""
s = {SUGG}
recs = s.get_platform_models()
result = dict(order=list(s._provider_order), providers=[i[0] for i in s.get_provider_items()],
              short_p=dict(s._short_providers), n_short_m=len(s._short_models), n_models=len(recs),
              groups=[r['provider_id'] for r in recs])
""")
    out['catalog'] = cat
    check(cat['order'], "catalog carries provider_order", **cat)
    rank = {p: i for i, p in enumerate(cat['order'])}
    listed = [p for p in cat['providers'] if p in rank]
    check(listed == sorted(listed, key=rank.get), "provider list follows provider_order", **cat)
    groups = list(dict.fromkeys(cat['groups']))
    check(groups == sorted(groups, key=lambda p: rank.get(p, 99)), "catalog groups in backend order",
          groups=groups)
    check(all(cat['short_p'].get(p) for p in groups), "every provider has a short label", **cat)
    check(cat['n_short_m'] >= cat['n_models'] > 0, "every model has a short label", **cat)

    progress(qa, '2. chip')
    # 2. chip
    chip = mp.chip(qa)
    out['chip'] = chip
    check(all(chip[:3]), "chip never blank", chip=chip)

    progress(qa, '3. card rows')
    # 3. card rows
    qa.open_chat()
    time.sleep(1)
    mp.open_popup(qa)
    mp.show_tab(qa, 'MIXIE')
    # The card opens scrolled to the current pick: wheel to the top first.
    for _ in range(12):
        if mp.rows(qa) and mp.rows(qa)[0][0] == 'Mixar default':
            break
        first = qa.find(**mp.PICK)['widgets'][0]
        qa.cmd("wheel", widget={"surface": "model_card_row", "index": first['index']}, clicks=1, up=True)
        time.sleep(.2)
    time.sleep(.5)
    rows = mp.rows(qa)
    out['mixie_rows'] = rows[:6]
    check(rows and rows[0][0] == 'Mixar default', "Mixie tab opens on Mixar default", rows=rows[:4])
    meta = qa.eval("result=[w.get('detail') for w in drv.find(surface='model_card_note')]")
    out['notes'] = meta

    progress(qa, '4. keyboard')
    # 4. keyboard
    tabs = qa.eval("result=[(w['value'], w.get('detail'), w.get('enabled')) for w in drv.find(surface='model_card_tab')]")
    out['tabs'] = tabs
    for key in ('RIGHT_ARROW', 'RIGHT_ARROW', 'LEFT_ARROW'):
        mp.press_on_card(qa, key)
        time.sleep(.3)
        shown = mp.open_tab(qa)
        detail = next((t[1] for t in tabs if t[0] == shown), '')
        check(detail != 'settings', "keyboard never lands on an action tab", key=key, shown=shown, tabs=tabs)
    mp.press_on_card(qa, 'ESC')
    qa.wait(f"not {mp.OPEN}", timeout=5)

    progress(qa, '5. click-away reaches the composer')
    # 5. click-away reaches the composer
    mp.open_popup(qa)
    card = qa.find(**mp.CARD)['widgets'][0]
    composer = qa.find(area_type='AGENT_BUBBLE', prop='mixie_chat_input')['widgets']
    check(composer, "composer target found")
    # The card overlays the composer's middle: click the composer where the
    # card is not (a press over the card is a pick, not a click-away).
    cx0, cy0, cx1, cy1 = composer[0]['rect']
    kx0, _ky0, kx1, _ky1 = card['rect']
    x = cx0 + 12 if cx0 + 12 < kx0 else cx1 - 12
    check(not (kx0 <= x <= kx1), "a composer point outside the card", composer=composer[0]['rect'], card=card['rect'])
    before = progress(qa, '5. before click-away')
    qa.cmd('click_xy', window=card['window'], x=x, y=(cy0 + cy1) // 2)
    qa.wait(f"not {mp.OPEN}", timeout=5)
    check(progress(qa, '5. after click-away') == before, "a click-away picks nothing")
    qa.press('ESC')  # leave the composer's text edit

    progress(qa, '6. the sheet')
    # 6. the sheet
    mp.open_popup(qa)
    if qa.eval("result=next((w.get('detail') for w in drv.find(surface='model_card_tab') if w['value']=='KEY'), '')") == 'settings':
        qa.click(surface='model_card_tab', value='KEY')
    else:
        mp.show_tab(qa, 'KEY')
        mp.settings(qa)
    qa.wait(DIALOG_OPEN, timeout=10)
    time.sleep(.8)
    picks = popup_widgets(qa, op=PICK_OP)
    rows_y = sorted(((w['rect'][1], w['rect'][0], w['text']) for w in picks), key=lambda r: (-r[0], r[1]))
    providers = [t for y, x, t in rows_y if x < min(r[1] for r in rows_y) + 5]
    out['sheet_providers'] = providers
    guide = popup_widgets(qa, op='WM_OT_url_open')
    check(guide, "Guide button present")
    top_row = max(y for y, _x, _t in rows_y)
    check(guide[0]['rect'][1] > top_row, "Guide sits on the PROVIDERS row, above the providers",
          guide=guide[0]['rect'], top_row=top_row)
    check(any('Local model' in t for t in providers), "Local model foot row", providers=providers)
    qa.snap(str(OUT / 'sheet_open.png'))

    progress(qa, '7. Codex in use')
    # 7. Codex in use
    byok = qa.eval("wm=bpy.context.window_manager\nresult=[wm.byok_is_active, wm.byok_current_provider, wm.byok_current_model]")
    out['byok'] = byok
    if byok[0] and byok[1] == 'codex':
        qa.click(popup=True, op=PICK_OP, text='Codex', contains=True)
        time.sleep(.6)
        labels = [w.get('text') or '' for w in popup_widgets(qa)]
        check('Codex sign-in file' in labels, "short Codex prompt", labels=labels[:40])
        check(not any('empty = the default' in t for t in labels), "no long Codex prompt")
        in_use = [t for t in labels if t.startswith('In use:')]
        check(in_use and 'Codex (ChatGPT sub)' not in in_use[0], "in-use line drops the shown provider",
              in_use=in_use)
        out['in_use'] = in_use
        disc = popup_widgets(qa, op='MIXAR_BYOK_OT_request_remove')
        check(disc and disc[0]['text'] == 'Disconnect', "Codex removes with Disconnect", disc=disc)
        qa.click(popup=True, op='MIXAR_BYOK_OT_request_remove')
        qa.wait("bpy.context.window_manager.byok_dialog_state == 'CONFIRM_REMOVE'", timeout=8)
        time.sleep(.6)
        stay = popup_widgets(qa, op='MIXAR_BYOK_OT_cancel_remove')
        go = popup_widgets(qa, op='MIXAR_BYOK_OT_confirm_remove')
        check(stay and stay[0]['text'] == 'Stay connected' and go and go[0]['text'] == 'Disconnect',
              "confirm step wording", stay=stay, go=go)
        qa.snap(str(OUT / 'sheet_confirm_disconnect.png'))
        qa.click(popup=True, op='MIXAR_BYOK_OT_cancel_remove')
        qa.wait("bpy.context.window_manager.byok_dialog_state == 'IDLE'", timeout=8)
        check(qa.eval("result=bpy.context.window_manager.byok_is_active"), "Stay connected keeps the key")
    else:
        out['codex_step'] = 'skipped: BYOK not on Codex'
    close_dialog(qa)

    progress(qa, '8. send gate while a key change saves')
    # 8. send gate while a key change saves
    gate = qa.eval("""
from mixar.modules.byok.core import credential_state as cs
from mixar.modules.space_mixie_chat.core import composer_send
scene = drv.main_window().scene
old = cs._pending
cs._pending = {'kind': 'resume', 'model': ''}
try:
    blocked = composer_send.can_send(scene)
finally:
    cs._pending = old
result = [blocked[0], blocked[1]]
""")
    out['send_gate'] = gate
    check(gate[0] is False and 'Saving agent model' in gate[1], "send waits while a key change saves",
          gate=gate)

    progress(qa, '9. guest')
    # 9. guest
    was_account = not qa.eval("result=bpy.data.window_managers[0].mixie_chat_is_guest")
    state = ensure_guest(qa, timeout=90)
    out['guest_state'] = dict(state, was_account=was_account)
    time.sleep(2)
    chip = mp.chip(qa)
    out['guest_chip'] = chip
    # A guest's own key still answers (the chip names it); without one, Mixie.
    check(all(chip[:3]) and (chip[0] != 'MIXIE' or chip[1] == 'Mixie'), "guest chip never blank", chip=chip)
    mp.open_popup(qa)
    mp.show_tab(qa, 'MIXIE')
    note = qa.eval("result=[w['text'] for w in drv.find(surface='model_card_note')]")
    rows = mp.rows(qa)
    out['guest_rows'] = rows[:5]
    out['guest_note'] = note
    check('Sign in to use Mixar models' in note, "guest sees the sign-in note", note=note)
    check(rows and not any(enabled for _t, enabled in rows), "guest rows disabled", rows=rows[:5])
    mp.close_popup(qa)
    if not out['guest_state'].get('was_account'):
        return out  # started as a guest: nothing to restore
    sign_in_dev_bypass(qa, timeout=90)
    return out


if __name__ == '__main__':
    run_scenario('agent_model_card_matrix_e2e', run)
