#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Onboarding tour telemetry and seen-state across real launches; no credits.

Regression for a customer whose ordinary quits read as a tour failure loop
(8 tour runs / 7 launches, every quit mid-tour reported ``failed``). Owns
its app process and a FRESH profile (no seeded ``onboarding_seen.json``, so
the first-run tour really auto-starts), relaunches it on the same profile,
and records analytics from inside the app through
``onboarding_tour_telemetry_probe.py`` (a profile startup module): nothing
is sent to the backend or PostHog. A fresh device signs in as a GUEST and
the tour starts at once; guests send no telemetry, so the first start is
asserted on the recorded ``capture`` call (calls.jsonl), then the scenario
signs in with the Dev bundle's dev-bypass account so every later event is
asserted on what the app actually delivers (events.jsonl). Two dev-bypass
logins per run (the backend allows 20 an hour).

  a. fresh profile → guest sign-in → the tour auto-starts, start_source=auto_signin
  b. past the first beat → onboarding_seen.json is {"seen": true}, no temp files
  c. quit mid-tour → tour_finished stop_reason=quit, outcome=interrupted
  d. relaunch → no auto-start after sign-in, nor after a Zen/Engine switch
  e. Help → Start tour → start_source=help_menu; Escape → Leave → exited
  f. corrupt seen file + read-only data dir → seen_state_error read/write,
     and the tour still auto-starts (fails open)

macOS. QA_HARNESS=<mixar-qa-harness> BUILD=<Mixar.app> \
QA_SCENARIO_OUT=<dir> python3 tests/qa/onboarding_tour_telemetry_e2e.py
The bundle must carry this branch's Python (scripts/mixar). Screenshots,
events.jsonl, app logs and verdict.json go to QA_SCENARIO_OUT.
"""
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
HARNESS = Path(os.environ['QA_HARNESS'])
sys.path.insert(0, str(HARNESS / 'scenarios'))
from lib import QA, ScenarioFail, set_mode  # noqa: E402

BUILD = Path(os.environ.get('BUILD', HERE.parents[1] / 'build/Dev/bin/Mixar.app'))
OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/onboarding-tour-telemetry'))
PROFILE = OUT / 'profile'
DATA = PROFILE / 'datafiles' / 'mixar'
SEEN = DATA / 'onboarding_seen.json'
EVENTS = OUT / 'events.jsonl'
CALLS = OUT / 'calls.jsonl'

SESSION = "__import__('mixar.modules.onboarding.core.tour.session', fromlist=['current']).current()"
RUNNING = f"({SESSION} is not None and {SESSION}.running)"
STATE = "__import__('json').loads(bpy.data.window_managers[0].mixar_tour_state or '{}')"


class App:
    """One app process on the scenario's profile; ``launch`` again to relaunch."""

    def __init__(self):
        self.process = None
        self.qa = None
        self.launches = 0

    def launch(self):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        self.launches += 1
        env = dict(os.environ, MIXAR_QA='1', MIXAR_QA_PORT=str(port),
                   MIXAR_USER_RESOURCES=str(PROFILE), MIXAR_QA_OUT=str(OUT),
                   MIXAR_QA_TELEMETRY_LOG=str(EVENTS),
                   MIXAR_QA_TELEMETRY_CALLS=str(CALLS),
                   MIXAR_OPERATION_HISTORY_DIR=str(OUT / 'ophistory'))
        log = (OUT / f'app-{self.launches}.log').open('w', encoding='utf-8')
        self.process = subprocess.Popen(
            [str(BUILD / 'Contents/MacOS/Mixar'), '-p', '60', '60', '1680', '1050',
             '--enable-event-simulate', '--python', str(HARNESS / 'driver/qa_server.py')],
            env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        self.qa = QA(port)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise ScenarioFail(f'app exited during startup ({self.process.returncode})')
            try:
                if self.qa.status()['logged_in']:
                    break
            except (OSError, ScenarioFail):
                pass
            time.sleep(.5)
        else:
            raise ScenarioFail('app never signed in')
        # Never deliver QA telemetry: the probe must own the worker's send.
        if self.qa.eval("import importlib\n"
                        "cap = importlib.import_module('mixar.modules.common.analytics.capture')\n"
                        "result = cap._post_batch.__name__") != 'record':
            raise ScenarioFail('telemetry probe not installed; refusing to run')
        return self.qa

    def quit(self, timeout=20):
        self.qa.cmd('quit')
        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            raise ScenarioFail(f'quit exceeded {timeout} s') from None
        return self.process.returncode

    def kill(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()


def events(name=None, since=0, source=EVENTS):
    if not source.exists():
        return []
    rows = [json.loads(line) for line in source.read_text().splitlines() if line.strip()]
    rows = rows[since:]
    return [e for e in rows if name is None or e['event'] == name]


def wait_event(name, since, predicate=lambda props: True, timeout=15, source=EVENTS):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = [e['properties'] for e in events(name, since, source)
                 if predicate(e['properties'])]
        if found:
            return found[-1]
        time.sleep(.25)
    raise ScenarioFail(f'no {name} in {source.name} since #{since}: '
                       f'{events(None, since, source)[-5:]}')


def mark(source=EVENTS):
    return len(events(source=source))


def sign_in_account(qa):
    """The product's sign-in operator; the Dev bundle's dev-bypass makes it a
    form login. A signed-in account is not a guest, so telemetry flows."""
    qa.eval("bpy.ops.mixie_chat.login()\nresult = True")
    qa.wait("not __import__('mixar.modules.auth.core.guest', fromlist=['is_guest'])"
            ".is_guest() and bpy.data.window_managers[0].mixie_chat_is_logged_in",
            timeout=60)


def snap(qa, name):
    path = OUT / f'{name}.png'
    qa.snap(str(path))
    return str(path)


def click_tour_control(qa, name):
    """Click one of the tour card's published control rects (main window)."""
    qa.wait(f"any(t['name'] == {name!r} for t in __import__('json').loads("
            "bpy.data.window_managers[0].mixar_tour_qa_targets or '[]'))", timeout=10)
    qa.eval("import json\n"
            "targets = json.loads(bpy.data.window_managers[0].mixar_tour_qa_targets)\n"
            f"x1, y1, x2, y2 = next(t['rect'] for t in targets if t['name'] == {name!r})\n"
            "result = drv.click_xy_steps(drv.main_window(), (x1 + x2) / 2, (y1 + y2) / 2)")


def escape_then_leave(qa):
    """Escape with the pointer over the host viewport, then Leave."""
    qa.eval("win = drv.main_window()\n"
            "area = next(a for a in win.screen.areas if a.type == 'VIEW_3D')\n"
            "x, y = area.x + area.width // 2, area.y + area.height // 3\n"
            "def esc():\n"
            "    drv.move_to(win, x, y)\n"
            "    drv._last_xy[win.as_pointer()] = (x, y)\n"
            "    yield .05\n"
            "    drv._sim(win, type='ESC', value='PRESS', x=x, y=y)\n"
            "    yield .03\n"
            "    drv._sim(win, type='ESC', value='RELEASE', x=x, y=y)\n"
            "    yield .1\n"
            "result = esc()")
    qa.wait(f"{SESSION} is not None and {SESSION}.exit_confirm", timeout=8)
    click_tour_control(qa, 'tour_confirm_exit')
    qa.wait(f"{SESSION} is None", timeout=10)


def past_first_beat(qa):
    """Next (the card's skip control) until the runner has left beat 0."""
    for _ in range(3):
        if qa.eval(f"result = {STATE}.get('index', 0)") >= 1:
            return
        click_tour_control(qa, 'tour_skip')
        time.sleep(.6)
    qa.wait(f"{STATE}.get('index', 0) >= 1", timeout=10)


def temp_files():
    """Leftovers of the atomic write (``.onboarding_seen.json.<random>``)."""
    return sorted(p.name for p in DATA.iterdir() if p.name.startswith('.' + SEEN.name))


def run():
    if PROFILE.exists():
        shutil.rmtree(PROFILE)
    EVENTS.unlink(missing_ok=True)
    CALLS.unlink(missing_ok=True)
    for part in ('scripts/startup', 'datafiles/mixar', 'config'):
        (PROFILE / part).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(HARNESS / 'qa_boot_startup.py', PROFILE / 'scripts/startup/qa_boot.py')
    shutil.copyfile(HERE / 'onboarding_tour_telemetry_probe.py',
                    PROFILE / 'scripts/startup/qa_tour_telemetry.py')
    verdict = {'steps': {}}
    app = App()
    try:
        # a. A device that never saw the tour: sign-in starts it.
        assert not SEEN.exists()
        since, calls_since = mark(), mark(CALLS)
        qa = app.launch()
        qa.dismiss_splash()
        qa.wait(RUNNING, timeout=30)
        started = wait_event('onboarding.tour_started', calls_since, source=CALLS)
        assert started['start_source'] == 'auto_signin', started
        identity = qa.eval("result = bpy.context.scene.mixie_chat_user_id")
        shot = snap(qa, 'a-auto-started')
        sign_in_account(qa)
        # The guest's start was gated, never delivered.
        assert events('onboarding.tour_started', since) == []
        verdict['steps']['a'] = {'tour_started_call': started, 'first_identity_is_guest':
                                 identity.endswith('@guest.mixar.invalid'),
                                 'delivered_while_guest': 0, 'screenshot': shot}

        # b. Past the first beat the device has seen it, written atomically.
        past_first_beat(qa)
        qa.wait(f"__import__('os').path.isfile({str(SEEN)!r})", timeout=5)
        seen = json.loads(SEEN.read_text())
        assert seen == {'seen': True}, seen
        assert temp_files() == [], temp_files()
        verdict['steps']['b'] = {'seen_file': seen, 'other_files': temp_files(),
                                 'beat': qa.eval(f"result = {STATE}.get('beat')")}

        # c. Quitting mid-tour is an interruption with its raw reason.
        assert qa.eval(f"result = {RUNNING}")
        code = app.quit()
        finished = wait_event('onboarding.tour_finished', since, timeout=5)
        assert finished['stop_reason'] == 'quit', finished
        assert finished['outcome'] == 'interrupted', finished
        assert finished['start_source'] == 'auto_signin', finished
        verdict['steps']['c'] = {'exit_code': code, 'tour_finished': finished}

        # d. Relaunch: the seen device gets no tour, not on sign-in and not
        #    after a Zen/Engine choice.
        since, calls_since = mark(), mark(CALLS)
        qa = app.launch()
        qa.dismiss_splash()
        time.sleep(4)
        assert qa.eval(f"result = {SESSION} is None")
        sign_in_account(qa)  # a second sign-in, now as the account
        time.sleep(4)
        assert qa.eval(f"result = {SESSION} is None")
        shot = snap(qa, 'd-relaunch-no-tour')
        modes = [set_mode(qa, 'engine'), set_mode(qa, 'zen')]
        time.sleep(4)
        assert qa.eval(f"result = {SESSION} is None")
        assert events('onboarding.tour_started', since) == []
        assert events('onboarding.tour_started', calls_since, CALLS) == []
        verdict['steps']['d'] = {'screenshot': shot, 'modes': modes,
                                 'tour_started_events': 0}

        # e. Help → Start tour replays it on a seen device; Escape → Leave.
        since = mark()
        qa.click(text='Help', but_type='Pulldown')
        qa.click(text='Start tour', popup=True)
        qa.wait(RUNNING, timeout=15)
        started = wait_event('onboarding.tour_started', since)
        assert started['start_source'] == 'help_menu', started
        shot = snap(qa, 'e-help-replay')
        escape_then_leave(qa)
        finished = wait_event('onboarding.tour_finished', since)
        assert (finished['outcome'], finished['stop_reason'], finished['start_source']) == \
            ('exited', 'exited', 'help_menu'), finished
        verdict['steps']['e'] = {'tour_started': started, 'tour_finished': finished,
                                 'screenshot': shot}

        # f. A corrupt seen file in a read-only data dir: both failures are
        #    reported (type names only) and the tour still starts.
        SEEN.write_text('{not json')
        DATA.chmod(stat.S_IRUSR | stat.S_IXUSR)
        try:
            since = mark()
            set_mode(qa, 'engine')
            qa.wait(RUNNING, timeout=20)
            read = wait_event('onboarding.seen_state_error', since,
                              lambda p: p['op'] == 'read')
            started = wait_event('onboarding.tour_started', since)
            past_first_beat(qa)
            write = wait_event('onboarding.seen_state_error', since,
                               lambda p: p['op'] == 'write')
            shot = snap(qa, 'f-fail-open-tour')
            escape_then_leave(qa)
        finally:
            DATA.chmod(stat.S_IRWXU)
        errors = [e['properties'] for e in events('onboarding.seen_state_error', since)]
        assert read['error'] == 'JSONDecodeError' and write['error'] == 'PermissionError', errors
        assert all(set(e) >= {'op', 'error'} and str(PROFILE) not in json.dumps(e)
                   for e in errors), errors
        assert started['start_source'] == 'auto_mode', started
        assert SEEN.read_text() == '{not json' and temp_files() == [], temp_files()
        verdict['steps']['f'] = {'seen_state_errors': [{k: e[k] for k in ('op', 'error')}
                                                       for e in errors],
                                 'tour_started': started, 'screenshot': shot}
        app.quit()
        verdict['ok'] = True
    except Exception as exc:
        verdict['ok'] = False
        verdict['failure'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        if DATA.exists():
            DATA.chmod(stat.S_IRWXU)
        app.kill()
        (OUT / 'verdict.json').write_text(json.dumps(verdict, indent=2, default=str))
        print(json.dumps(verdict, indent=2, default=str))
    return verdict


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        run()
    except Exception:
        sys.exit(1)
