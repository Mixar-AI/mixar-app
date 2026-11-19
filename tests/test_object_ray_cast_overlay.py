# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Exercise the actual evaluation helper with minimal native API stand-ins.

The real RNA / executor integration is exercised by mixar-qa-harness release
case AP-2006 (`scenarios/ray_cast_no_mesh_e2e.py`).
"""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/source/blender/makesrna/intern/rna_object_api.cc"
# A linked worktree (`<checkout>/.worktrees/<name>`) has no submodule checkout of
# its own; read the main checkout's, as `settings.sh` does.
UPSTREAM_CANDIDATES = (
    ROOT / "upstream/source/blender/makesrna/intern/rna_object_api.cc",
    ROOT.parents[1] / "upstream/source/blender/makesrna/intern/rna_object_api.cc",
)
MIXAR_SPDX = " * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited\n"
# Upstream checks for an evaluated mesh only inside the `data_eval == nullptr`
# branch; the overlay hoists the check out of it.
UPSTREAM_GUARD = """\
  if (ob->runtime->data_eval == nullptr) {
    Object *ob_orig = ob;
    Depsgraph *depsgraph = rnaptr_depsgraph != nullptr ?
                               static_cast<Depsgraph *>(rnaptr_depsgraph->data) :
                               nullptr;
    if (depsgraph == nullptr) {
      depsgraph = CTX_data_ensure_evaluated_depsgraph(C);
    }
    if (depsgraph != nullptr) {
      ob = DEG_get_evaluated(depsgraph, ob);
    }
    if (ob == nullptr || BKE_object_get_evaluated_mesh(ob) == nullptr) {
      BKE_reportf(
          reports, RPT_ERROR, "Object '%s' has no evaluated mesh data", ob_orig->id.name + 2);
      return nullptr;
    }
  }
"""
OVERLAY_GUARD = """\
  Object *ob_orig = ob;
  if (ob->runtime->data_eval == nullptr) {
    Depsgraph *depsgraph = rnaptr_depsgraph != nullptr ?
                               static_cast<Depsgraph *>(rnaptr_depsgraph->data) :
                               nullptr;
    if (depsgraph == nullptr) {
      depsgraph = CTX_data_ensure_evaluated_depsgraph(C);
    }
    if (depsgraph != nullptr) {
      ob = DEG_get_evaluated(depsgraph, ob);
    }
  }
  /* Evaluated data can be a non-mesh component (for example, Curves). Check even
   * when data_eval was already populated, before either mesh query dereferences it. */
  if (ob == nullptr || BKE_object_get_evaluated_mesh(ob) == nullptr) {
    BKE_reportf(
        reports, RPT_ERROR, "Object '%s' has no evaluated mesh data", ob_orig->id.name + 2);
    return nullptr;
  }
"""
HUNKS = ((UPSTREAM_GUARD, OVERLAY_GUARD),)


def test_evaluated_data_is_not_necessarily_a_mesh(tmp_path):
    compiler = shutil.which("c++")
    if not compiler:
        pytest.skip("C++ compiler unavailable")
    text = SOURCE.read_text()
    helper = text[text.index("static Object *eval_object_ensure("):
                  text.index("static void rna_Object_ray_cast(")]
    code = r"""
#include <cassert>
struct Runtime { void *data_eval; };
struct ID { char name[16] = "OBfixture"; };
struct Object { Runtime *runtime; bool mesh; ID id; };
struct Depsgraph { Object *evaluated; };
struct bContext { Depsgraph *graph; };
struct ReportList { int errors = 0; };
struct PointerRNA { void *data; };
constexpr int RPT_ERROR = 1;
void BKE_reportf(ReportList *r, int, const char *, const char *) { r->errors++; }
Depsgraph *CTX_data_ensure_evaluated_depsgraph(bContext *c) { return c->graph; }
Object *DEG_get_evaluated(Depsgraph *g, Object *) { return g->evaluated; }
void *BKE_object_get_evaluated_mesh(Object *o) { return o->mesh ? o : nullptr; }
"""
    code += helper
    code += r"""
int main() {
  int data = 0;
  Runtime populated{&data}, missing{nullptr};
  Object nonmesh{&populated, false}, mesh{&populated, true};
  Object original{&missing, false};
  Depsgraph graph{&mesh};
  bContext context{&graph};
  ReportList reports;
  // Regression: non-null data_eval with no mesh used to bypass validation.
  assert(eval_object_ensure(&nonmesh, &context, &reports, nullptr) == nullptr);
  assert(reports.errors == 1);
  assert(eval_object_ensure(&mesh, &context, &reports, nullptr) == &mesh);
  assert(eval_object_ensure(&original, &context, &reports, nullptr) == &mesh);
  graph.evaluated = &nonmesh;
  assert(eval_object_ensure(&original, &context, &reports, nullptr) == nullptr);
  graph.evaluated = nullptr;
  assert(eval_object_ensure(&original, &context, &reports, nullptr) == nullptr);
  assert(reports.errors == 3);
  Depsgraph explicit_graph{&mesh};
  PointerRNA pointer{&explicit_graph};
  assert(eval_object_ensure(&original, &context, &reports, &pointer) == &mesh);
}
"""
    source = tmp_path / "query.cc"
    binary = tmp_path / "query"
    source.write_text(code)
    subprocess.run([compiler, "-std=c++17", str(source), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)


def test_the_overlay_only_differs_from_upstream_in_the_intended_hunks():
    """Keep the overlay a one-hunk patch so an upstream bump is a re-copy."""
    upstream = next((p for p in UPSTREAM_CANDIDATES if p.exists()), None)
    if upstream is None:
        pytest.skip("pinned upstream checkout unavailable")
    up = upstream.read_text(encoding="utf-8")
    if UPSTREAM_GUARD not in up:
        pytest.skip("the pin carries an eval_object_ensure fix: drop the overlay")
    patched = up
    for old, new in HUNKS:
        assert patched.count(old) == 1, old.splitlines()[0]
        patched = patched.replace(old, new)
    overlay = SOURCE.read_text(encoding="utf-8")
    assert overlay.count(MIXAR_SPDX) == 1
    assert overlay.replace(MIXAR_SPDX, "", 1) == patched
