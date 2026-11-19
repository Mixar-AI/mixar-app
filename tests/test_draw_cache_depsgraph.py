# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Execute the shipped cache sweep against checked graph/iterator doubles.

`DRW_cache_free_old_batches` must skip a depsgraph that is not fully evaluated
(mixar-backend#2027): a scene no window shows keeps a stale graph after a delete
and the object iterator read its freed `id_orig`. Blender 5.3 carries that guard
itself (upstream a3889bb09e4, "Fix #163701: crash during viewport garbage
collector"), so Mixar ships upstream's `draw_context.cc` with no overlay. The
sweep that ships is compiled here; the control is the same function with the
guard removed, which is the code Blender 5.2 shipped.

Dirty graphs deliberately reject iteration before any object is dereferenced.
This is a control-flow regression, not a native lifetime or GPU integration test.
"""
from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
REL = Path('source/blender/draw/intern/draw_context.cc')
QUERY_REL = Path('source/blender/depsgraph/intern/depsgraph_query.cc')
OVERLAY = ROOT / 'src' / REL
# A linked worktree (`<checkout>/.worktrees/<name>`) has no submodule checkout of
# its own; read the main checkout's, as `settings.sh` does.
UPSTREAM_ROOTS = (ROOT / 'upstream', ROOT.parents[1] / 'upstream')
SIGNATURE = 'void DRW_cache_free_old_batches('
GUARD = re.compile(
    r'[ \t]*if \(!DEG_is_fully_evaluated\(depsgraph\)\) \{\n[ \t]*continue;\n[ \t]*\}\n')


def upstream(rel):
    path = next((root / rel for root in UPSTREAM_ROOTS if (root / rel).exists()), None)
    if path is None:
        pytest.skip(f'upstream checkout required: {rel}')
    return path.read_text()


def function(text, signature):
    start = text.index(signature)
    return text[start:text.index('\n}', start) + 2]


def shipped_sweep():
    """The sweep the build compiles: `src/` is overlaid on top of upstream."""
    text = OVERLAY.read_text() if OVERLAY.exists() else upstream(REL)
    return function(text, SIGNATURE)


def unguarded_sweep():
    sweep, removed = GUARD.subn('', function(upstream(REL), SIGNATURE))
    assert removed == 1, 'the control needs exactly one readiness guard to remove'
    return sweep


@pytest.mark.parametrize('unfixed', [False, True], ids=['fixed', 'unfixed-control'])
def test_sweep_defers_dirty_graphs(tmp_path, unfixed):
    compiler = shutil.which('c++')
    if not compiler:
        pytest.skip('C++ compiler required')
    sweep = unguarded_sweep() if unfixed else shipped_sweep()
    query = function(upstream(QUERY_REL), 'bool DEG_is_fully_evaluated(')
    program = r'''
#include <cassert>
#include <cstdlib>
#include <vector>
namespace blender { namespace draw {} }
struct Tags { bool empty = true; bool is_empty() const { return empty; } };
namespace deg { struct Depsgraph { bool need_update_relations = false; Tags entry_tags; }; }
using Depsgraph = deg::Depsgraph;
struct Object {};
struct ViewLayer { Depsgraph *graph; };
struct Scene { struct { void *next = nullptr; } id; std::vector<ViewLayer> view_layers; };
struct SceneList { Scene *head; Scene *first() const { return head; } };
struct Main { SceneList scenes; };
struct { int vbotimeout = 1, vbocollectrate = 1; } U;
static int now = 100, freed = 0;
double BLI_time_now_seconds() { return now; }
Depsgraph *BKE_scene_get_depsgraph(Scene *, ViewLayer *layer) { return layer->graph; }
QUERY
struct DEGObjectIterSettings { Depsgraph *depsgraph; int flags; };
constexpr int DEG_OBJECT_ITER_FOR_RENDER_ENGINE_FLAGS = 123;
Object *checked_object(DEGObjectIterSettings *settings) {
  assert(settings->flags == DEG_OBJECT_ITER_FOR_RENDER_ENGINE_FLAGS);
  if (!DEG_is_fully_evaluated(settings->depsgraph)) std::exit(86);
  static Object object;
  return &object;
}
#define DEG_OBJECT_ITER_BEGIN(settings, ob) { Object *ob = checked_object(settings);
#define DEG_OBJECT_ITER_END }
void DRW_batch_cache_free_old(Object *, int time) { assert(time == now); ++freed; }
SWEEP
int main() {
  Depsgraph clean, relations, updates;
  relations.need_update_relations = true;
  updates.entry_tags.empty = false;
  Scene first, second;
  first.id.next = &second;
  first.view_layers = {{nullptr}, {&clean}};
  second.view_layers = {{&relations}, {&updates}};
  Main main{{&first}};
  DRW_cache_free_old_batches(&main);
  assert(freed == 1); // A dirty layer cannot prevent another scene's collection.
  DRW_cache_free_old_batches(&main);
  assert(freed == 1); // Existing throttle remains intact.
  relations.need_update_relations = false;
  updates.entry_tags.empty = true;
  ++now;
  DRW_cache_free_old_batches(&main);
  assert(freed == 4); // Deferred graphs rejoin collection after evaluation.
  ++now;
  U.vbotimeout = 0;
  DRW_cache_free_old_batches(&main);
  assert(freed == 4);
}
'''.replace('QUERY', query).replace('SWEEP', sweep)
    source = tmp_path / 'sweep.cc'
    source.write_text(program)
    binary = tmp_path / 'sweep'
    built = subprocess.run([compiler, '-std=c++17', str(source), '-o', str(binary)],
                           capture_output=True, text=True)
    assert built.returncode == 0, built.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True)
    assert result.returncode == (86 if unfixed else 0), result.stderr


def test_upstream_guard_ships_without_an_overlay():
    """The pin owns the guard, so a whole-file overlay would only shadow upstream."""
    sweep = function(upstream(REL), SIGNATURE)
    guard = GUARD.search(sweep)
    if guard is None:
        pytest.fail(
            'upstream DRW_cache_free_old_batches no longer skips depsgraphs that are not '
            'fully evaluated (mixar-backend#2027): restore the guard in a fenced '
            'draw_context.cc overlay',
            pytrace=False,
        )
    assert guard.start() < sweep.index('DEG_OBJECT_ITER_BEGIN')
    assert not OVERLAY.exists(), (
        'src/source/blender/draw/intern/draw_context.cc shadows upstream, which already '
        'skips dirty depsgraphs: delete the overlay')
