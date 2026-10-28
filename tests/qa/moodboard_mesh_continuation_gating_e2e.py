# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""No-credit QA scenario: the mesh `+` menu offers only features its card can run.

A mesh node's output `+` used to list Smart UV whenever ``uv_unwrapping`` had
any service, while Node Templates keep only the services the card executes
(``tripo_uv``). On a backend serving just ``hunyuan_uv`` the card then read
"Model unavailable". Mesh Segmentation had the same mismatch (its card runs
``hunyuan_part``; catalogs serve ``tripo_segment``).

Checks, with real clicks on the real `+` menu:
1. the live catalog: Smart UV is offered, and the `+` mesh entries equal the
   mesh templates (Mesh Segmentation is in neither unless ``hunyuan_part`` is
   served);
2. a catalog where ``uv_unwrapping`` serves only ``hunyuan_uv``, swapped in
   memory on the client only: Smart UV is gone from `+` and from Templates;
3. the live catalog restored: Smart UV is back.

Launch a fresh isolated app (``$QA_HARNESS/run_qa_app_parallel.sh``), then:
    QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=<port> \\
        python3 tests/qa/moodboard_mesh_continuation_gating_e2e.py
Uses ``QA_SCENARIO_OUT`` when set. Nothing is submitted. Vision: the first and
last menu snapshots list Smart UV, the middle one does not.
"""

import json
import os
from pathlib import Path
import sys
import tempfile

MESH = "QA_Plus_Menu_Mesh"
MENU_OP = "MIXIE_OT_moodboard_create_connected_action"

FIXTURE = f'''
w = drv.main_window()
assert {MESH!r} not in bpy.data.objects, "Start a fresh QA instance"
me = bpy.data.meshes.new({MESH!r})
me.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
obj = bpy.data.objects.new({MESH!r}, me)
w.scene.collection.objects.link(obj)
for o in w.view_layer.objects:
    o.select_set(o is obj)
w.view_layer.objects.active = obj
result = True
'''

# Client-only, in memory: uv_unwrapping serves hunyuan_uv instead of tripo_uv.
SIMULATE = '''
import copy, sys, types
from mixar.bootstrap import generation_catalog_cache as cache
state = sys.modules.setdefault("qa_plus_gating_state", types.ModuleType("qa_plus_gating_state"))
with cache._lock:
    state.original = cache._catalog
    fake = copy.deepcopy(cache._catalog)
    cap = next(c for c in fake["capabilities"] if c.get("key") == "uv_unwrapping")
    service = copy.deepcopy(cap["services"][0])
    service.update(key="hunyuan_uv", name="Hunyuan UV Unwrap")
    for model in service.get("models") or []:
        model["slug"] = "hunyuan_uv_v1"
    cap["services"] = [service]
    cache._catalog = fake
    cache._bump_enum_version_locked()
result = [s["key"] for s in cache.get_services("uv_unwrapping")]
'''

RESTORE = '''
import sys
from mixar.bootstrap import generation_catalog_cache as cache
state = sys.modules.pop("qa_plus_gating_state", None)
if state is not None:
    with cache._lock:
        cache._catalog = state.original
        cache._bump_enum_version_locked()
result = [s["key"] for s in cache.get_services("uv_unwrapping")]
'''

TEMPLATES = '''
from mixar.modules.moodboard.core.node_templates import available_templates
result = [t[0] for t in available_templates()]
'''


def plus_menu(qa, source, out, label):
    """Open the source node's `+` menu like a user; return its entries."""
    qa.click(surface="moodboard_output", text=source)
    qa.wait(f"bool(drv.find(popup=True, op={MENU_OP!r}))", timeout=6)
    entries = [w["text"] for w in qa.find(popup=True, op=MENU_OP)["widgets"]]
    path = str(out / f"plus-menu-{label}.png")
    # Centred on Retopology (offered in every case) so the whole menu fits.
    qa.cmd("snap", path=path, target={"popup": True, "op": MENU_OP, "text": "Retopology"},
           margin=170)
    qa.press("ESC")
    qa.wait("not drv.find(popup=True)", timeout=5)
    return {"entries": entries, "templates": qa.eval(TEMPLATES), "snapshot": path}


MESH_ENTRIES = {"PBR Generation": "PBR_GEN", "Retopology": "RETOPOLOGY",
                "Mesh Segmentation": "MESH_SEGMENT", "Smart UV": "UV_UNWRAP",
                "Auto Rig": "AUTO_RIG"}


def agree(menu):
    offered = {MESH_ENTRIES[t] for t in menu["entries"] if t in MESH_ENTRIES}
    return offered == set(menu["templates"]) & set(MESH_ENTRIES.values())


def run(qa):
    sys.path.insert(0, str(Path(os.environ["QA_HARNESS"]) / "scenarios"))
    import lib

    out = Path(os.environ.get("QA_SCENARIO_OUT", tempfile.mkdtemp(prefix="qa-plus-gating-")))
    out.mkdir(parents=True, exist_ok=True)
    assert qa.eval('import os; result = os.environ.get("MIXAR_QA") == "1"')
    qa.cmd("wait_login", timeout=90)
    qa.wait(lib.CATALOG_LOADED, timeout=45)
    lib.ensure_scenes_drawer(qa)
    lib.ensure_moodboard_area(qa)
    qa.step("fixture", qa.eval, FIXTURE)
    host = qa.eval("result=drv.moodboard_host()")
    qa.click(area_type=host["area_type"], text="Add media or selected scene meshes")
    qa.wait("bool(drv.find(popup=True,op='MIXIE_OT_add_selected_mesh_to_moodboard'))", timeout=6)
    qa.click(popup=True, op="MIXIE_OT_add_selected_mesh_to_moodboard")
    qa.wait("len(drv.main_window().scene.mixie_moodboard_asset_nodes)==1", timeout=6)
    source = qa.eval("result=drv.main_window().scene.mixie_moodboard_asset_nodes[0].node_id")
    qa.press("HOME")
    evidence = {}
    evidence["live"] = live = qa.step("live catalog menu", plus_menu, qa, source, out, "live")
    assert "Smart UV" in live["entries"] and agree(live), live
    try:
        evidence["simulated_services"] = qa.step("simulate hunyuan_uv only", qa.eval, SIMULATE)
        assert evidence["simulated_services"] == ["hunyuan_uv"], evidence
        evidence["hunyuan_only"] = sim = qa.step(
            "hunyuan-only menu", plus_menu, qa, source, out, "hunyuan-uv-only")
        assert "Smart UV" not in sim["entries"] and "UV_UNWRAP" not in sim["templates"], sim
        assert agree(sim), sim
    finally:
        evidence["restored_services"] = qa.step("restore catalog", qa.eval, RESTORE)
    assert "tripo_uv" in evidence["restored_services"], evidence
    evidence["restored"] = back = qa.step("restored menu", plus_menu, qa, source, out, "restored")
    assert "Smart UV" in back["entries"] and agree(back), back
    assert qa.eval("result=len(drv.main_window().scene.mixie_moodboard_action_nodes)==0")
    (out / "plus-gating-evidence.json").write_text(json.dumps(evidence, indent=2))
    return {"evidence": str(out / "plus-gating-evidence.json"),
            "snapshots": [evidence[k]["snapshot"] for k in ("live", "hunyuan_only", "restored")],
            "backend_submissions": 0, "credits_spent": 0}


if __name__ == "__main__":
    sys.path.insert(0, str(Path(os.environ["QA_HARNESS"]) / "scenarios"))
    from lib import run_scenario

    run_scenario("moodboard_mesh_continuation_gating", run)
