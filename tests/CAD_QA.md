<!-- SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited -->
<!-- SPDX-License-Identifier: GPL-2.0-or-later -->

# CAD cleanup regression and application checks

The standalone naming suite runs without Blender:

```powershell
python -m pytest -q tests/test_cad_cleanup_rules.py
```

The real geometry fixture deliberately uses a renamed vehicle collection with a
nested collection containing a comma. It includes the historical naming failures,
thin released geometry, a 2 cm sensor, parented nonuniform scale, topology and UV
adversaries, a rotated duplicate, and an outside-scope hidden sentinel. It creates
a new scene and does not delete or reset any existing data.

Run the fixture in a fresh, isolated process:

```powershell
& 'C:/Program Files/Blender Foundation/Blender 5.1/blender.exe' --background --factory-startup --python tests/cad_cleanup_blender_qa.py -- --out D:/metadome/_cad_work/evidence/blender
```

This checks recursive scope, analysis without mutation, owner isolation, retry
idempotence, stage execution, geometry preservation, restoration of memberships,
and save gates. It writes the source fixture, PNG evidence, and JSON report.
The report intentionally remains `visual_review_pending=true`; a test program
cannot certify that someone looked at the image.

For application validation, launch the real built Mixar app using the QA harness
with its isolated resources profile, set `QA_HARNESS` to that harness root, and run
`python tests/cad_cleanup_gui_scenario.py`. Set `CAD_QA_CLIENT_ROOT` if testing
staged sources rather than the checkout. The scenario uses tool dispatch directly
because this capability has no new UI controls; it frames the real viewport and
captures a screenshot. It makes no provider calls and spends no generation credits.

Inspect both `cad-cleanup-evidence.png` and `cad-cleanup-viewport.png`. After looking
at the images, finish from the same live application through the QA driver's eval:

```python
result = cadqa.finish_after_visual_review(
    "Reviewed rendered geometry and viewport; thin panel and small sensor remain present."
)
```

Replace the example notes with what was actually observed. This separately tests
output/source collision rejection, traversal rejection, saving a fresh artifact,
save retry idempotence, and unchanged source bytes. No full customer vehicle or
backend service is required for these local checks. A real agent chat run and a
visually reviewed customer vehicle remain separate acceptance checks.

After delivery, call `cadqa.check_saved_reopen()` in the isolated fixture app to
reopen the generated output and validate persisted stage status, start/resume,
and replay of the original successful save request.

Additional adversarial checks run in separate fresh Blender processes with
`--python tests/cad_cleanup_adversarial_qa.py`. The default case covers explicit
unit correction, scale baking, undo, missing recovery dependencies, external mesh
changes, stale proposals, and retry with an expected revision. Pass
`-- --duplicate-visibility` to check that a hidden shared-mesh reference cannot
remove its visible twin. Pass `-- --failed-apply` to check complete rollback of
objects and collection structure after a destination ancestor collision.

Use `--python-exit-code 1` when scripting Blender checks: Blender otherwise exits
with status zero even when a Python assertion fails. Always inspect the emitted
`CAD_ADVERSARIAL_RESULT` and exceptions as well as the process return code.

`cad_cleanup_policy_qa.py` adds seven real Blender checks: modifier/constraint RNA
snapshot, bevel parameter changes invalidating previews, inactive constraint
parameter changes being detected, presentation hide/show/undo, refusal to hide
review parts, refusal to accept an unproven duplicate, and refusal to bake a
sheared dependency transform. Run it in the same fresh background configuration.

Validation recorded on Blender 5.1.1: these seven policy checks passed, alongside
44 naming regressions and the ten adversarial lifecycle checks. The isolated
Mixar GUI run separately passed saved-file reopen and save-request replay;
its evidence is recorded in `_cad_work/evidence/gui/cad-cleanup-qa.json` in the
implementation workspace. These fixture results do not claim full vehicle-level
classification accuracy or a provider-backed agent chat run.

Full-assembly QA found redundant reverse-membership scans and repeated dependency updates.
CAD tools now index membership/parents per operation and batch collection moves before
restoring per-view-layer visibility. Apply retains full before/after geometry checks.
Inspection pages explicitly distinguish live metadata from stored proposal snapshots
and report live_geometry_checked=false. Browsing does not rehash mesh data; analysis,
mutation preflight, verification, and delivery retain full geometry checks.
`tests/cad_cleanup_index_qa.py` checks shared/excluded collection equivalence and
rejects applying a stored preview after an external scene edit.

Snapshot version 2 records authored transform channels and parent inverse. Classification
compares those settings rather than unevaluated world-matrix caches on excluded objects.
Undo/rollback batches membership restoration and never writes a stale cached world
matrix back through a parent. Older cleanup runs fail closed and require the original
project. Test with tests/cad_cleanup_excluded_transform_qa.py; add -- --forced-rollback
to exercise failure recovery and bounded dependency-graph updates.

## Checkpoint validation (supersedes per-call full auditing)

CAD validation uses checkpoint snapshots (version 3). Baseline/final delivery
audits hash all meshes in the selected run scope. Routine reads do not audit geometry;
mutation metadata checks reuse expected mesh hashes. Geometry edits audit their target
meshes before/after; cad_verify(stage=...) audits the stage's affected objects and
shared data, ignoring unrelated collection geometry. External geometry changes can
remain undetected until their checkpoint or final audit; cached hashes are not fresh
evidence. The write boundary audits again to reject edits after final verification.
Final completeness verification refuses pending stages before scanning meshes. Backend
completion consumes the saved integrity receipt without a redundant post-save audit.
Grouped category summaries permit focused semantic review; samples are not exhaustive.
Lightweight scene metadata still checks scope and dependency changes globally.

Run tests/cad_cleanup_checkpoint_qa.py in a fresh background Blender process.

CAD inspection rendering removes temporary object/scene/camera IDs with one
bpy.data.batch_remove call. Per-object remove causes minutes of relationship scans
on full assemblies. Never include source meshes/materials in the deletion batch.
tests/cad_cleanup_render_cleanup_qa.py validates success and injected-failure cleanup.

CAD render evidence retains at most eight PNGs in the app's temporary inspection
directory. An identical revision/fingerprint/view/target retry returns the same
evidence ID and pixels with cached=true, allowing recovery after a WebSocket drops
a long render response. Missing cache files regenerate. Local image filenames stay
in client run state; they never appear in the tool response. This does not prevent
the first blocking render from losing its connection; it makes that result retryable.
tests/cad_cleanup_render_recovery_qa.py checks retry persistence and invalidation.


Reference workflow fixture: run the built app with --background --factory-startup
--disable-autoexec --python tests/cad_cleanup_reference_qa.py in an isolated QA
profile. It checks native visibility vs occlusion, exact camera rays, invalid
regions, cached view reuse, no omission from visibility absence, incomplete and
single-view delivery refusal, reference-only export, and source-ID preservation.
This fixture does not establish Gemini accuracy or full-vehicle acceptance.

Native CAD raster capture uses the existing scene and a nonblocking Eevee render
job, with ray tracing/compositing/motion blur disabled. Subsets link original objects into a temporary collection/view layer; whole-scene
capture reuses the original layer. This avoids per-object hide/restore across the
assembly. Camera, world, render settings and the few changed visibility flags are
restored on completion. Setup, render and restoration timings are reported separately. CAD mutations are refused
while the job runs. cad_render/cad_status return running; retry the identical
cad_render to retrieve completed pixels and stable source-object IDs. No full-car
mesh-count restriction applies. Ray selection reuses the current evaluated scene;
hidden subsets absent from that graph fail explicitly rather than inventing hits.
tests/cad_cleanup_raster_job_qa.py checks the real GUI job and restored state.


## CAD decision evidence after Run09

Assembly inspection and reference assignment share current category/path constraints;
specific current descriptors supersede stale diagnostic labels. Rejections expose
bounded conflicting IDs and compatible/conflict selections. Known PneuNuPRV and
front-bumper-lower-grille phrases are normalized conservatively; unrelated substrings
and competing components stay unresolved. Exact reference paths are unchanged.

Wheel variant keeps require `cad_review_wheel` and `wheel_review_id`: immutable
original object/parent descriptors must explicitly establish inch size and construction,
then an independent Gemini review of the exact scoped image must identify complete
wheel geometry. Generic Jante/rim names, outer diameter and existing assignments are
not variant proof. Source failures skip the provider. Identical visual failures are
cached and cannot be overwritten by retrying. A new image or corrected selection is
required for new review. Provider uncertainty/unavailability leaves the variant unresolved.
This is an additional fallible visual opinion, not guaranteed geometric recognition.
Only wheel variant receipts without this proof become invalid; unrelated policy-2
receipts are retained. Scope, path, image and scene revision bind the wheel receipt.

The lane batches related reads and changes rejected membership/evidence rather than
retrying identical decisions with rewritten prose. Subset renders do not call final
cad_review. Major-batch index.html checkpoints and final delivery gates remain required.
Client fixture `tests/cad_cleanup_decision_qa.py` tests the gates using synthetic review
responses. Actual provider accuracy and the agent workflow must be retested on UAT
after backend sync and client rebuild; backend runtime tests are not run locally.


## Organized CAD checkpoints and retained internals

Major reference checkpoints materialize a separate `CAD Organized` scene with
shared mesh data and independent objects. Accepted keeps use populated exact
reference paths and their ancestors; unresolved, invalid and pending objects use
one `REVIEW`; identified concealed mechanisms use `HIDDEN_INTERNALS` with viewport
and render disabled. Diagnostic groups remain recovery-only. Empty owned shells
are removed, foreign collection-name collisions fail without taking ownership.
Organization checks changed target metadata, never mesh buffers, and does not
change source memberships/revision or invalidate source evidence. Status and HTML
report actual organized counts separately from planned assignments and flag stale
organization. Saved checkpoints contain the resumable recovery state plus a
separate `organized.mixar` inspection copy; only milestone saves write projects.
Final export retains hidden internals and rejects unresolved semantic coverage.
Unsupported animated/constrained/modified dependency graphs still block export.

`hidden_internal` decisions require scoped semantic evidence, a current enclosing
assembly image including the targets, and explicit exterior AND cabin visibility
reasoning. A raster miss or system-name classification alone cannot justify hiding.
The agent prioritizes broad exterior/cabin coverage and continues past unavailable
wheel-variant evidence. Wheel synonyms do not introduce output collections.

Validation: `tests/cad_cleanup_organized_qa.py` exercises real Blender memberships,
zero geometry hashing at organization, shared mesh preservation, empty collection
cleanup, collision refusal, hidden evidence gates and saved checkpoint copies.
Synthetic evidence tests protocol only; full UAT visual classification is separate.
