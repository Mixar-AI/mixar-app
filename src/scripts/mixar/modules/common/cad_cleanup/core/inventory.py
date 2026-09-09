# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Reusable metadata inventory. Queries are snapshots, never geometry verification."""
from collections import Counter
import bpy
from . import state, reference, assignment_receipts

_cache = None


def index(run, refresh=False):
    global _cache
    key = (bpy.context.scene.as_pointer(), run['run_id'], run['revision'])
    if refresh or _cache is None or _cache[0] != key:
        objects = state.objects(run)
        relations = (*state.relations(), state.render_eligible_ids())
        rows = {k:state.record(o,k,run,relations) for k,o in objects.items()}
        _cache = (key, rows)
    return _cache[1]
