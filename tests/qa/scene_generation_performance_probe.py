# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Temporary probes, loaded with QA eval into an isolated GUI process.

Records main-loop gaps and phase timings without changing execution policy.
Set MIXAR_QA_OUT at launch. Restart the QA app to remove all instrumentation.
"""
import functools
import faulthandler
import json
import os
import time
from pathlib import Path

import bpy

from mixar.modules.space_mixie_chat.core import main_thread_executor as mt
from mixar.modules.space_mixie_chat.core.executor import ScriptExecutor

ROOT = Path(os.environ['MIXAR_QA_OUT'])
TIMINGS = open(ROOT / 'scene-performance.jsonl', 'a', buffering=1)
STACKS = open(ROOT / 'scene-performance-stacks.txt', 'a', buffering=1)
SEQ = 0
LAST_TICK = time.monotonic()
LAST_LOG = 0


def record(kind, **data):
    TIMINGS.write(json.dumps(dict(kind=kind, wall=time.time(), **data)) + '\n')


def wrap(owner, name):
    original = getattr(owner, name)

    @functools.wraps(original)
    def timed(*args, **kwargs):
        start = time.monotonic()
        try:
            return original(*args, **kwargs)
        finally:
            record('phase', phase=name, seconds=time.monotonic() - start)

    setattr(owner, name, timed)


for phase in ('route_request', 'restore_after', 'archive_history'):
    wrap(mt, phase)
for phase in ('_capture_scene_state', '_push_undo_checkpoint', '_detect_changes'):
    wrap(ScriptExecutor, phase)

original_execute = ScriptExecutor.execute


@functools.wraps(original_execute)
def execute(self, script, *args, **kwargs):
    global SEQ
    SEQ += 1
    seq = SEQ
    (ROOT / f'performance-script-{seq:04}.py').write_text(script)
    record('script_start', seq=seq, info=mt.get_inflight_script(),
           objects=len(bpy.data.objects))
    start = time.monotonic()
    try:
        return original_execute(self, script, *args, **kwargs)
    finally:
        record('script_end', seq=seq, seconds=time.monotonic() - start,
               objects=len(bpy.data.objects))


ScriptExecutor.execute = execute


def heartbeat():
    global LAST_TICK, LAST_LOG
    now = time.monotonic()
    gap = now - LAST_TICK
    LAST_TICK = now
    if gap > .5 or now - LAST_LOG > 5:
        record('heartbeat', gap=gap, objects=len(bpy.data.objects),
               inflight=mt.get_inflight_script())
        LAST_LOG = now
    faulthandler.cancel_dump_traceback_later()
    faulthandler.dump_traceback_later(3, repeat=True, file=STACKS)
    return .1


bpy.app.timers.register(heartbeat, first_interval=.1, persistent=True)
record('instrumentation_ready', pid=os.getpid())
