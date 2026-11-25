# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Collection.all_objects membership edits inside a Python loop: no backend, no credits.

Replays mixar-backend#1978 (Linux crash in ``Collection_all_objects_next`` <-
``pyrna_prop_collection_iter_next`` while an agent script changed collection
membership inside ``for o in coll.all_objects``). The native iterator walks
``collection->runtime->object_cache`` Base nodes; any link, unlink or delete
frees that cache while the iterator already points at the next node. The
``bpy_rna.cc`` overlay (``MIXAR-1978`` fences) makes Python iterate a snapshot
of the object wrappers instead; ID free invalidates a wrapper, so a deleted
object's entry raises ReferenceError on attribute access.

Every case is a plain ``for o in parent.all_objects:`` loop sent with
``qa.eval``, which execs directly and so bypasses the agent executor's AST
transform (the transform's protection is not what is under test). Each case
builds its own uniquely named parent/child collections (NOT linked to the
scene) holding N objects, some linked in both so de-duplication is exercised,
and removes everything it made afterwards. A case whose build or body raises
records ``{'error': repr(exc)}`` (cleanup and pid still recorded) and counts as
a mismatch, so the remaining cases still replay on the unfixed build.

Expected on the fixed build (N = 300):
- unlink: unlinking every visited object from every collection visits all N
  once, in the original order, and leaves ``len(parent.all_objects) == 0``.
  Measured on the unfixed macOS build: 2 visited, 298 left (freed cache nodes
  read as end-of-list); on Linux the loop can crash the app;
- delete_current: removing each visited object visits all N, none left;
- delete_next: removing the NEXT object through ``bpy.data.objects[name]``
  turns its snapshot entry into a ReferenceError on ``.name``: N-1 readable,
  1 ReferenceError at that index;
- add: objects linked inside the loop are not visited: exactly the original N;
- delete_parent: removing the owning collection mid-loop keeps iterating over
  the surviving objects, all readable;
- comprehension: ``[bpy.data.objects.remove(o, do_unlink=True) for o in
  parent.all_objects]`` removes all N;
- early_exit: ``break`` and ``next(iter(...))`` return the first object of
  ``list(parent.all_objects)``;
- the same app process (pid) answers before and after every case.

Replay: QA_HARNESS=../mixar-qa-harness MIXAR_QA_PORT=<port>
QA_SCENARIO_OUT=<dir> python3 tests/qa/all_objects_iteration_e2e.py
"""
import json
import os
from pathlib import Path
import sys

_HARNESS = os.environ.get('QA_HARNESS') or str(Path(__file__).resolve().parents[3] / 'mixar-qa-harness')
sys.path.insert(0, str(Path(_HARNESS) / 'scenarios'))
from lib import ScenarioFail, run_scenario  # noqa: E402

N = 300
SCENARIO = 'all_objects_iteration'

PROCESS = '''
import os
assert os.environ.get('MIXAR_QA') == '1'
result = {'pid': os.getpid(), 'version': bpy.app.version_string,
          'build_hash': bpy.app.build_hash.decode(), 'objects': len(bpy.data.objects)}
'''

# Shared helpers, prepended to every case. Cleanup goes by the case's unique
# name prefix through bpy.data, so it never touches a removed object's wrapper.
PRELUDE = '''
import os, uuid

def _build(key, n):
    parent = bpy.data.collections.new(key + '_parent')
    child = bpy.data.collections.new(key + '_child')
    parent.children.link(child)
    for i in range(n):
        o = bpy.data.objects.new('%s_%03d' % (key, i), None)
        if i % 7 == 3:
            parent.objects.link(o)
        else:
            child.objects.link(o)
            if i % 5 == 0:
                parent.objects.link(o)  # in both: all_objects must list it once
    original = [o.name for o in parent.all_objects]
    assert len(original) == n == len(set(original)), (len(original), len(set(original)))
    return parent, child, original

def _cleanup(key):
    for data in (bpy.data.collections, bpy.data.objects):
        for item in [i for i in data if i.name.startswith(key)]:
            try:
                data.remove(item, do_unlink=True)
            except Exception:
                pass  # e.g. a freed wrapper on an unfixed build; counted below
    return {'collections': sum(1 for c in bpy.data.collections if c.name.startswith(key)),
            'objects': sum(1 for o in bpy.data.objects if o.name.startswith(key))}

def _alive(names):
    return sum(1 for name in names if bpy.data.objects.get(name) is not None)

def _run_case(case, body, n):
    # A build or body error is recorded, not raised: cleanup still runs and the
    # later cases still replay (an 'error' key always counts as a mismatch).
    key = 'QA1978_%s_%s' % (case, uuid.uuid4().hex[:8])
    try:
        out = body(key, *_build(key, n))
    except Exception as exc:
        out = {'error': repr(exc)}
    finally:
        try:
            leftover = _cleanup(key)
        except Exception as exc:
            leftover = {'error': repr(exc)}  # a LEFT mismatch, never an abort
    out.update(pid=os.getpid(), leftover=leftover)
    return out
'''

UNLINK = '''
def _unlink(key, parent, child, original):
    visited = []
    for o in parent.all_objects:
        visited.append(o.name)
        for coll in (parent, child):
            if coll.objects.get(o.name) is not None:
                coll.objects.unlink(o)
    return {'visited': len(visited), 'unique': len(set(visited)), 'in_order': visited == original,
            'left_in_all_objects': len(parent.all_objects)}
result = _run_case('unlink', _unlink, N)
'''

DELETE_CURRENT = '''
def _delete_current(key, parent, child, original):
    visited = []
    for o in parent.all_objects:
        visited.append(o.name)
        bpy.data.objects.remove(o, do_unlink=True)
    return {'visited': len(visited), 'in_order': visited == original,
            'left_in_all_objects': len(parent.all_objects), 'left_in_data': _alive(original)}
result = _run_case('delete_current', _delete_current, N)
'''

DELETE_NEXT = '''
def _delete_next(key, parent, child, original):
    at = len(original) // 2
    readable, dead = [], []
    for i, o in enumerate(parent.all_objects):
        try:
            readable.append(o.name)
        except ReferenceError:
            dead.append(i)
            continue
        if i == at:
            bpy.data.objects.remove(bpy.data.objects[original[at + 1]], do_unlink=True)
    return {'visited': len(readable) + len(dead), 'readable': len(readable),
            'reference_errors': len(dead), 'dead_at_deleted_index': dead == [at + 1],
            'readable_in_order': readable == original[:at + 1] + original[at + 2:],
            'left_in_all_objects': len(parent.all_objects)}
result = _run_case('delete_next', _delete_next, N)
'''

ADD = '''
def _add(key, parent, child, original):
    visited, added = [], []
    for i, o in enumerate(parent.all_objects):
        visited.append(o.name)
        if i % 10 == 0:
            new = bpy.data.objects.new('%s_add_%03d' % (key, i), None)
            (parent if i % 20 == 0 else child).objects.link(new)
            added.append(new.name)
    return {'visited': len(visited), 'in_order': visited == original,
            'added_visited': len(set(added) & set(visited)), 'added': len(added),
            'left_in_all_objects': len(parent.all_objects)}
result = _run_case('add', _add, N)
'''

DELETE_PARENT = '''
def _delete_parent(key, parent, child, original):
    at = len(original) // 3
    readable, errors = [], 0
    for i, o in enumerate(parent.all_objects):
        try:
            readable.append(o.name)
        except ReferenceError:
            errors += 1
        if i == at:
            bpy.data.collections.remove(parent)
    return {'visited': len(readable) + errors, 'reference_errors': errors,
            'in_order': readable == original,
            'parent_gone': bpy.data.collections.get(key + '_parent') is None,
            'survivors': _alive(original)}
result = _run_case('delete_parent', _delete_parent, N)
'''

COMPREHENSION = '''
def _comprehension(key, parent, child, original):
    removed = [bpy.data.objects.remove(o, do_unlink=True) for o in parent.all_objects]
    return {'visited': len(removed), 'left_in_all_objects': len(parent.all_objects),
            'left_in_data': _alive(original)}
result = _run_case('comprehension', _comprehension, N)
'''

EARLY_EXIT = '''
def _early_exit(key, parent, child, original):
    listed = list(parent.all_objects)
    loop_first = None
    for o in parent.all_objects:
        loop_first = o.name
        break
    it = iter(parent.all_objects)
    taken = [next(it).name for _ in range(5)]
    rest = list(it)
    return {'list_first': listed[0].name == original[0], 'break_first': loop_first == original[0],
            'next_first': next(iter(parent.all_objects)).name == original[0],
            'taken_in_order': taken == original[:5], 'rest': len(rest), 'exhausted': list(it) == []}
result = _run_case('early_exit', _early_exit, N)
'''

LEFT = {'leftover': {'collections': 0, 'objects': 0}}
CASES = (
    ('unlink', UNLINK, {'visited': N, 'unique': N, 'in_order': True, 'left_in_all_objects': 0}),
    ('delete_current', DELETE_CURRENT,
     {'visited': N, 'in_order': True, 'left_in_all_objects': 0, 'left_in_data': 0}),
    ('delete_next', DELETE_NEXT,
     {'visited': N, 'readable': N - 1, 'reference_errors': 1, 'dead_at_deleted_index': True,
      'readable_in_order': True, 'left_in_all_objects': N - 1}),
    ('add', ADD,
     {'visited': N, 'in_order': True, 'added_visited': 0, 'added': N // 10,
      'left_in_all_objects': N + N // 10}),
    ('delete_parent', DELETE_PARENT,
     {'visited': N, 'reference_errors': 0, 'in_order': True, 'parent_gone': True, 'survivors': N}),
    ('comprehension', COMPREHENSION, {'visited': N, 'left_in_all_objects': 0, 'left_in_data': 0}),
    ('early_exit', EARLY_EXIT,
     {'list_first': True, 'break_first': True, 'next_first': True, 'taken_in_order': True,
      'rest': N - 5, 'exhausted': True}),
)


def _write_evidence(evidence):
    out = os.environ.get('QA_SCENARIO_OUT')
    if not out:
        return
    path = Path(out)
    path.mkdir(parents=True, exist_ok=True)
    (path / f'{SCENARIO}.json').write_text(json.dumps(evidence, indent=2, default=str) + '\n')


def _run(qa, evidence):
    qa.step('dismiss_splash', qa.dismiss_splash)
    before = evidence['before'] = qa.step('process_before', qa.eval, PROCESS)
    mismatches = []
    for name, code, want in CASES:
        got = qa.step(name, qa.eval, f'N = {N}\n' + PRELUDE + code)
        evidence['cases'][name] = got
        diff = {k: (got.get(k), v) for k, v in {**want, **LEFT}.items() if got.get(k) != v}
        if 'error' in got:
            diff['error'] = (got['error'], None)
        if got.get('pid') != before['pid']:
            diff['pid'] = (got.get('pid'), before['pid'])
        if diff:
            mismatches.append(f'{name}: {diff}')
    after = evidence['after'] = qa.step('process_after', qa.eval, PROCESS)
    if after['pid'] != before['pid']:
        raise ScenarioFail(f"app restarted: pid {before['pid']} -> {after['pid']}")
    if mismatches:
        raise ScenarioFail('all_objects iteration (got, want): ' + '; '.join(mismatches))
    return {'pid': before['pid'], 'build_hash': before['build_hash'], 'cases': evidence['cases']}


def run(qa):
    evidence = {'scenario': SCENARIO, 'n': N, 'ok': False, 'cases': {}}
    try:
        verdict = _run(qa, evidence)
        evidence['ok'] = True
        return verdict
    except Exception as exc:
        evidence['failure'] = str(exc)
        raise
    finally:
        _write_evidence(evidence)


if __name__ == '__main__':
    run_scenario(SCENARIO, run)
