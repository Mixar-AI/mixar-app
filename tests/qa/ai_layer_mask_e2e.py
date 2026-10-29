#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Generate Mask with AI in the real GUI. FREE: no provider call, no credits.

Nothing reaches the backend's job route: the job-queue service's ``enqueue``
is stubbed in-process (calls recorded, never sent) around every UI submit, and
the agent-path capture stubs ``enqueue_generation``. Catalog edits are
in-process only. Every stub and edit is restored in ``finally``.

Proves through the real UI (Engine > Texturing, Layers header > Add Mask >
Image Masks > Generate Mask with AI...):
  1. the dialog has Describe / Placement (Anywhere, Crevices, Corners, Upward
     Faces, Edges) / Model, and the model list is the brush_gen catalog;
  2. the dialog opens on the catalog's DEFAULT brush_gen model, not the first
     model by sort order: the real default; then the default moved to the last
     model (in-process, sort order unchanged); then back. With the catalog
     unloaded it shows "No models available" and OK is refused; after OK with
     another model the dialog reopens on the default again (the remembered
     pick is not "passed");
  3. OK with an empty description is refused ("Describe the mask first");
  4. two objects whose same-named layers ("Fill Layer") get the same
     description queue TWO jobs; the same target again is refused ("This mask
     is already being generated"), and so is a linked duplicate sharing the
     crate's paint material (same layer); the Queue mirror rows and the
     enqueue toast show only the description, never the dedup identity;
  5. agent-path targeting (object_name + layer_index) builds a brush_gen job
     with purpose=layer_mask whose label names the target layer;
  6. simulated delivery after a reorder attaches an IMAGE mask on the layer the
     job was requested for (found by group node);
  7. simulated delivery after the layer is deleted keeps the image and raises
     the "Mask not added to the layer" warning toast.

Run against an already running QA app, from a clean file:
  QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4808 \\
  QA_SCENARIO_OUT=/tmp/aimask python3 tests/qa/ai_layer_mask_e2e.py
Read the PNGs as well as the verdict.
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(os.environ["QA_HARNESS"]) / "scenarios"))
from lib import CATALOG_LOADED, ScenarioFail, run_scenario  # noqa: E402

OUT = Path(os.environ.get("QA_SCENARIO_OUT", "/tmp")) / "ai_layer_mask"
ADD_MASK_TIP = "Add different types of masks to the active layer"
OP = "WM_OT_m_generate_layer_mask"
DESCRIPTION = "rust streaks"
MP = ("__import__('mixar.modules.paint.core.node.node_utils', fromlist=['x'])"
      ".get_active_mpaint_node().node_tree.mp")

SETUP = f"""
from mixar.modules.paint.core.agent_tools.layer_stack import initialize_layer_paint_project
crate = bpy.data.objects.get('QA_Crate') or bpy.data.objects.get('Cube')
crate.name = 'QA_Crate'
if 'QA_Barrel' not in bpy.data.objects:
    bpy.ops.mesh.primitive_cylinder_add(location=(3.0, 0.0, 0.0))
    bpy.context.active_object.name = 'QA_Barrel'
stacks = {{}}
for name in ('QA_Barrel', 'QA_Crate'):
    initialize_layer_paint_project([name])
    obj = bpy.data.objects[name]
    for o in bpy.context.view_layer.objects: o.select_set(False)
    obj.select_set(True); bpy.context.view_layer.objects.active = obj
    if name == 'QA_Crate':
        have = [l.name for l in {MP}.layers]
        for n in ('Paint Base', 'Rust Coat'):
            if n not in have:
                bpy.ops.wm.m_new_layer('EXEC_DEFAULT', type='COLOR', add_mask=False, name=n)
    stacks[name] = [l.name for l in {MP}.layers]
result = stacks
"""

ACTIVATE = """
obj = bpy.data.objects[%r]
for o in bpy.context.view_layer.objects: o.select_set(False)
obj.select_set(True); bpy.context.view_layer.objects.active = obj
result = obj.name
"""

DEFAULT_LABEL = """
from mixar.bootstrap import generation_catalog_cache as g
slug = g.get_default_model_slug('brush_gen')
result = dict(slug=slug, label=(g.get_model('brush_gen', slug) or {}).get('label'),
              order=[m.get('slug') for m in g.get_models('brush_gen')])
"""

# Move the brush_gen default to the LAST model (sort order unchanged), so
# item 0 is no longer the default. None = unload. Originals kept for restore.
CATALOG_EDIT = """
import copy
from mixar.bootstrap import generation_catalog_cache as g
ns = bpy.app.driver_namespace
with g._lock:
    if 'qa_mask_catalog' not in ns:
        ns['qa_mask_catalog'] = g._catalog
    cat = None
    if %(mode)r == 'last_default':
        cat = copy.deepcopy(ns['qa_mask_catalog'])
        for cap in cat.get('capabilities') or []:
            for svc in cap.get('services') or []:
                if svc.get('key') == 'brush_gen':
                    models = svc.get('models') or []
                    for m in models:
                        m['is_default'] = m is models[-1]
    g._catalog = cat
    g._bump_enum_version_locked()
result = g.get_default_model_slug('brush_gen')
"""

CATALOG_RESTORE = """
from mixar.bootstrap import generation_catalog_cache as g
ns = bpy.app.driver_namespace
with g._lock:
    if 'qa_mask_catalog' in ns:
        g._catalog = ns.pop('qa_mask_catalog')
        g._bump_enum_version_locked()
result = g.is_loaded()
"""

STUB_SUBMIT = """
import mixar.modules.common.api.services.job_queue_service as J
svc = J.get_job_queue_service()
calls = bpy.app.driver_namespace['qa_mask_submits'] = []
svc.enqueue = lambda **kw: calls.append(
    {k: v for k, v in kw.items() if k in ('job_type', 'model', 'payload')})
result = 'enqueue' in vars(svc)
"""

# Cancel (no backend id, so no backend call), clear, drop the stub.
UNSTUB_SUBMIT = """
import mixar.modules.common.api.services.job_queue_service as J
from mixar.modules.common.job_queue.core.queue_manager import get_queue
q = get_queue('layer_mask_gen')
for job in q.snapshot():
    q.cancel(job.id)
q.clear_completed()
svc = J.get_job_queue_service()
if 'enqueue' in vars(svc):
    del svc.enqueue
result = dict(stub_removed='enqueue' not in vars(svc), left=len(q.snapshot()))
"""

QUEUE_STATE = """
from mixar.modules.common.job_queue.core.queue_manager import get_queue
from mixar.modules.common.notifications.store import get_notification_store
pg = bpy.context.window_manager.mixie_queue
result = dict(
    submits=bpy.app.driver_namespace.get('qa_mask_submits', []),
    jobs=[dict(label=j.label, display_label=j.display_label, state=j.state.value)
          for j in get_queue('layer_mask_gen').snapshot()],
    mirror=[dict(label=i.label, display_label=i.display_label)
            for i in pg.items if i.feature_key == 'layer_mask_gen'],
    toasts=[f"{getattr(t, 'title', '')} | {getattr(t, 'body', '')}"
            for t in get_notification_store().get_visible()],
)
"""

CAPTURE = """
import mixar.modules.common.job_queue as jq
ns = bpy.app.driver_namespace
cap = ns.setdefault('qa_caps', [])
orig = jq.enqueue_generation
jq.enqueue_generation = lambda **kw: (cap.append(kw), object())[1]
try:
    r = bpy.ops.wm.m_generate_layer_mask('EXEC_DEFAULT', prompt=%(prompt)r, model='pro',
        object_name='QA_Crate', layer_index=%(index)d, location=%(loc)r)
finally:
    jq.enqueue_generation = orig
kw = cap[-1]
result = dict(op=str(r), restored=jq.enqueue_generation is orig, idx=len(cap) - 1,
              label=kw['label'], job_type=kw['job_type'], feature_key=kw['feature_key'],
              payload=kw['payload'])
"""

DELIVER = """
kw = bpy.app.driver_namespace['qa_caps'][%(cap)d]
img = bpy.data.images.get(%(img)r) or bpy.data.images.new(%(img)r, 64, 64)
kw['on_imported'](None, %(img)r)
from mixar.modules.common.notifications import get_notification_store
mp = %(mp)s
result = dict(masks={l.group_node: [(m.name, m.type) for m in l.masks] for l in mp.layers},
              image=bpy.data.images.get(%(img)r) is not None,
              toasts=[getattr(t, 'title', '') for t in get_notification_store().get_visible()])
"""


def popup_widgets(qa):
    return qa.cmd("dump", popup=True, limit=60)["widgets"]


def dialog_props(qa):
    return {w.get("prop"): w.get("text") for w in popup_widgets(qa) if w.get("prop")}


def open_dialog(qa):
    """Masks > Image Masks > Generate Mask with AI...; returns {prop: shown text}.

    The first click after a popup closes can be swallowed, so a menu that
    did not open is retried once (state-checked, never blind)."""
    for _attempt in range(2):
        qa.click(area_type="MIXAR_LAYERS", text=ADD_MASK_TIP, but_type="Pulldown")
        if "Image Masks" not in [w.get("text") for w in popup_widgets(qa)]:
            continue  # the Masks menu click was swallowed
        qa.click(popup=True, text="Image Masks", but_type="Pulldown")
        if OP not in [w.get("op") for w in popup_widgets(qa)]:
            raise ScenarioFail("Image Masks menu has no Generate Mask with AI entry")
        qa.click(popup=True, op=OP)
        props = dialog_props(qa)
        if {"prompt", "location", "model"} <= set(props):
            return props
        qa.press("ESC")
    raise ScenarioFail(f"dialog did not open: {dialog_props(qa)}")


def close_dialog(qa):
    qa.press("ESC")
    deadline = time.monotonic() + 5
    while "prompt" in dialog_props(qa):
        if time.monotonic() > deadline:
            raise ScenarioFail("Esc did not close the dialog")
        time.sleep(0.1)


def dropdown_items(qa, prop):
    qa.click(popup=True, prop=prop)
    return [w.get("text") for w in popup_widgets(qa) if w.get("type") == "ButMenu"]


def select_layer(qa, name):
    for _attempt in range(2):  # a first click after a popup closes can be swallowed
        qa.click(area_type="MIXAR_LAYERS", text=name, op="LAYERS_OT_select_layer")
        got = qa.eval(f"result = {MP}.layers[{MP}.active_layer_index].name")
        if got == name:
            return
    raise ScenarioFail(f"could not select {name}: active={got}")


def submit_via_dialog(qa, obj, description):
    """Open the dialog on ``obj``'s active layer, describe, OK; new reports."""
    qa.eval(ACTIVATE % obj)
    before = qa.eval("result = len(bpy.context.window_manager.reports)")
    props = open_dialog(qa)
    qa.cmd("set_text", widget={"prop": "prompt", "popup": True}, text=description)
    qa.click(popup=True, text="OK", but_type="But")
    reports = qa.eval("result = [r.message for r in bpy.context.window_manager.reports]")
    return props, reports[before:]


def check_default_preselection(qa):
    """The dialog opens on the catalog default, wherever it sorts."""
    seen = {}
    try:
        real = qa.eval(DEFAULT_LABEL)
        if len(real["order"]) < 2:
            raise ScenarioFail(f"brush_gen needs two models to tell default from first: {real}")
        for step, mode in (("real", None), ("last_default", "last_default"), ("restored", None)):
            if mode:
                qa.eval(CATALOG_EDIT % dict(mode=mode))
            elif step == "restored":
                qa.eval(CATALOG_RESTORE)
            want = qa.eval(DEFAULT_LABEL)
            shown = open_dialog(qa)["model"]
            qa.snap(str(OUT / f"default_{step}.png"))
            close_dialog(qa)
            seen[step] = dict(default=want["slug"], shown=shown, order=want["order"])
            if shown != want["label"]:
                raise ScenarioFail(f"{step}: dialog shows {shown!r}, catalog default is {want}")
        if seen["last_default"]["default"] == seen["real"]["order"][0]:
            raise ScenarioFail(f"the moved default is still item 0: {seen}")

        qa.eval(CATALOG_EDIT % dict(mode="unloaded"))
        qa.eval(STUB_SUBMIT)  # a refusal that fails must still not reach the backend
        props, reports = submit_via_dialog(qa, "QA_Crate", DESCRIPTION)
        qa.snap(str(OUT / "default_unloaded_refused.png"))
        submits = qa.eval("result = len(bpy.app.driver_namespace['qa_mask_submits'])")
        if props["model"] != "No models available" or \
                "No mask generation model is available" not in reports or submits:
            raise ScenarioFail(f"unloaded catalog: {props} {reports} submits={submits}")
        seen["unloaded"] = dict(shown=props["model"], reports=reports)
    finally:
        qa.eval(CATALOG_RESTORE)
        qa.eval(UNSTUB_SUBMIT)
    return seen


def check_reopen_after_ok(qa):
    """OK with a non-default model, then reopen: the dialog is on the default."""
    try:
        qa.eval(STUB_SUBMIT)
        want = qa.eval(DEFAULT_LABEL)["label"]
        qa.eval(ACTIVATE % "QA_Crate")
        open_dialog(qa)
        other = [m for m in dropdown_items(qa, "model") if m != want][0]
        qa.click(popup=True, text=other, but_type="ButMenu")
        qa.cmd("set_text", widget={"prop": "prompt", "popup": True}, text="qa reopen")
        qa.click(popup=True, text="OK", but_type="But")
        submits = qa.eval("result = [c['model'] for c in "
                          "bpy.app.driver_namespace['qa_mask_submits']]")
        shown = open_dialog(qa)["model"]
        qa.snap(str(OUT / "reopen_after_ok.png"))
        close_dialog(qa)
        if shown != want:
            raise ScenarioFail(f"after OK with {other!r} the dialog reopened on {shown!r}, "
                               f"not the default {want!r} (submits {submits})")
        return dict(picked=other, reopened=shown, submits=submits)
    finally:
        qa.eval(UNSTUB_SUBMIT)


TWIN_ADD = """
crate = bpy.data.objects['QA_Crate']
twin = bpy.data.objects.get('QA_Twin') or crate.copy()   # linked: shares mesh + material
twin.name = 'QA_Twin'; twin.location.x = crate.location.x + 6.0
if twin.name not in bpy.context.scene.collection.all_objects:
    bpy.context.scene.collection.objects.link(twin)
result = twin.data == crate.data
"""

TWIN_REMOVE = """
twin = bpy.data.objects.get('QA_Twin')
if twin: bpy.data.objects.remove(twin)
result = 'QA_Twin' not in bpy.data.objects
"""


def check_duplicate_identity(qa):
    """Same layer name + description in two materials: two jobs; same target
    (also from a linked duplicate sharing the material): one."""
    try:
        qa.eval(STUB_SUBMIT)
        if not qa.eval(TWIN_ADD):
            raise ScenarioFail("QA_Twin does not share QA_Crate's mesh")
        runs = []
        for obj in ("QA_Crate", "QA_Barrel", "QA_Crate", "QA_Barrel", "QA_Twin"):
            _props, reports = submit_via_dialog(qa, obj, DESCRIPTION)
            runs.append((obj, reports[-1:]))
        accepted = [r for _o, r in runs[:2]]
        refused = [r for _o, r in runs[2:]]
        if any(r != ["Generating a mask for 'Fill Layer'..."] for r in accepted):
            raise ScenarioFail(f"two objects did not both queue: {runs}")
        if any(r != ["This mask is already being generated"] for r in refused):
            raise ScenarioFail(f"the same target was not refused: {runs}")
        qa.wait("len([i for i in bpy.context.window_manager.mixie_queue.items "
                "if i.feature_key == 'layer_mask_gen']) == 2", timeout=10)
        state = qa.eval(QUEUE_STATE)
        qa.snap(str(OUT / "two_objects_queued.png"))
        labels = [j["label"] for j in state["jobs"]]
        if len(state["submits"]) != 2 or len(set(labels)) != 2:
            raise ScenarioFail(f"expected two distinct jobs: {state}")
        if any(row["display_label"] != DESCRIPTION for row in state["mirror"]) \
                or len(state["mirror"]) != 2:
            raise ScenarioFail(f"Queue rows are not the clean description: {state['mirror']}")
        suffixes = [label.rsplit(" [", 1)[1] for label in labels]
        if any(s in toast for s in suffixes for toast in state["toasts"]) or \
                not any(DESCRIPTION in toast for toast in state["toasts"]):
            raise ScenarioFail(f"enqueue toast is not clean: {state['toasts']}")
        return dict(runs=runs, labels=labels, mirror=state["mirror"], toasts=state["toasts"],
                    submits=state["submits"])
    finally:
        qa.eval(UNSTUB_SUBMIT)
        qa.eval(TWIN_REMOVE)


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.wait(CATALOG_LOADED, timeout=30)
    stacks = qa.step("setup", qa.eval, SETUP)
    if "Fill Layer" not in stacks["QA_Crate"] or "Fill Layer" not in stacks["QA_Barrel"]:
        raise ScenarioFail(f"both objects need a Fill Layer: {stacks}")
    qa.cmd("set_mode", mode="engine")
    qa.cmd("workspace", name="Texturing")
    qa.eval(ACTIVATE % "QA_Crate")
    select_layer(qa, "Paint Base")

    open_dialog(qa)
    places = dropdown_items(qa, "location")
    if places != ["Anywhere", "Crevices", "Corners", "Upward Faces", "Edges"]:
        raise ScenarioFail(f"placements: {places}")
    qa.click(popup=True, text="Crevices", but_type="ButMenu")
    models = dropdown_items(qa, "model")
    catalog = qa.eval("from mixar.bootstrap.generation_catalog_cache import get_models\n"
                      "result = [m.get('label') for m in get_models('brush_gen')]")
    if models != catalog:
        raise ScenarioFail(f"models {models} vs catalog {catalog}")
    qa.click(popup=True, text=catalog[0], but_type="ButMenu")
    qa.click(popup=True, text="OK", but_type="But")      # empty description
    last = qa.eval("result = [r.message for r in bpy.context.window_manager.reports][-1:]")
    if last != ["Describe the mask first"]:
        raise ScenarioFail(f"empty description not refused: {last}")

    preselection = qa.step("default_model", check_default_preselection, qa)
    reopen = qa.step("reopen_after_ok", check_reopen_after_ok, qa)

    qa.eval(ACTIVATE % "QA_Crate")
    select_layer(qa, "Fill Layer")
    duplicates = qa.step("duplicate_identity", check_duplicate_identity, qa)

    # agent-path targeting + simulated delivery after a reorder
    qa.eval(ACTIVATE % "QA_Crate")
    layers = qa.eval(f"result = [(l.name, l.group_node) for l in {MP}.layers]")
    idx = [n for n, _ in layers].index("Rust Coat")
    group = dict(layers)["Rust Coat"]
    cap = qa.eval(CAPTURE % dict(prompt="qa rust", index=idx, loc="CAVITY"))
    if not (cap["restored"] and cap["job_type"] == "brush_gen"
            and cap["feature_key"] == "layer_mask_gen"
            and cap["payload"] == {"prompt": "qa rust", "purpose": "layer_mask",
                                   "location_hint": "CAVITY"}
            and cap["label"].startswith("Mask: Rust Coat: qa rust [")):
        raise ScenarioFail(f"capture: {cap}")
    select_layer(qa, "Rust Coat")
    qa.click(area_type="MIXAR_LAYERS", text="Move Down")
    got = qa.eval(DELIVER % dict(cap=cap["idx"], img="qa_mask_rust", mp=MP))
    if not any(t == "IMAGE" for _, t in got["masks"].get(group, [])):
        raise ScenarioFail(f"mask not on Rust Coat after reorder: {got}")
    qa.snap(str(OUT / "attached.png"))

    # deleted layer: image kept, warning toast
    idx = qa.eval(f"result = [l.name for l in {MP}.layers].index('Paint Base')")
    cap2 = qa.eval(CAPTURE % dict(prompt="qa moss", index=idx, loc="DUST"))
    select_layer(qa, "Paint Base")
    qa.eval("result = str(bpy.ops.layers.remove_active_layer('EXEC_DEFAULT', confirm=True))")
    got = qa.eval(DELIVER % dict(cap=cap2["idx"], img="qa_mask_moss", mp=MP))
    if not got["image"] or "Mask not added to the layer" not in got["toasts"]:
        raise ScenarioFail(f"deleted-layer path: {got}")
    qa.snap(str(OUT / "deleted_toast.png"))
    return {"models": models, "placements": places, "preselection": preselection,
            "reopen": reopen, "duplicates": duplicates, "agent_label": cap["label"]}


if __name__ == "__main__":
    run_scenario("ai_layer_mask_e2e", run)
