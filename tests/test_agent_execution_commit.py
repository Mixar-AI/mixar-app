# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Typed append_collection commit (harness v3) against a fake bpy."""

import hashlib
import os
import sys
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

_SRC_SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "scripts"))
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)
for _dep in ("keyring", "websocket", "requests", "jwt", "sentry_sdk"):
    sys.modules.setdefault(_dep, MagicMock(name=_dep))

from mixar.modules.common.agent_execution import bindings, commit, document, paths  # noqa: E402
from mixar.modules.common.agent_execution.journal import APPLIED, Journal  # noqa: E402

IDENTITY = {"document_id": "doc", "document_epoch": 1, "scene_id": "sc", "scene_name": "Scene"}


class FakeObj:
    def __init__(self, name):
        self.name = name
        self.selected = False

    def select_set(self, v):
        self.selected = v


class FakeCollection:
    def __init__(self, name, objects=()):
        self.name = name
        self.all_objects = list(objects)
        self.children = FakeChildren()


class FakeChildren(list):
    def get(self, name):
        return next((c for c in self if c.name == name), None)

    def link(self, c):
        self.append(c)


class FakeCollections(list):
    def get(self, name):
        return next((c for c in self if c.name == name), None)

    def new(self, name):
        c = FakeCollection(name)
        self.append(c)
        return c


class FakeBpy:
    """Just enough of bpy for append_collection."""

    def __init__(self, library_collections=("wc_task1",), fail_load=False):
        objs = [FakeObj("Cube"), FakeObj("Cube.001")]
        self._lib = {name: FakeCollection(name, objs) for name in library_collections}
        self.fail_load = fail_load
        self.loads = []
        self.data = SimpleNamespace(collections=FakeCollections(), libraries=SimpleNamespace(load=self._load))
        scene = SimpleNamespace(collection=FakeCollection("Scene Collection"), camera="CAM", name="Scene")
        self.user = [FakeObj("UserCube")]
        self.user[0].selected = True
        self.context = SimpleNamespace(
            scene=scene, mode="OBJECT",
            window_manager=SimpleNamespace(mixie_instance_id="inst", is_interface_locked=False),
            view_layer=SimpleNamespace(objects=SimpleNamespace(active=self.user[0])),
            selected_objects=self.user,
        )
        self.context.scene.get = lambda k, d=None: d
        self.context.scene.__setitem__ = lambda k, v: None

    @contextmanager
    def _load(self, path, link=False):
        assert link is False, "must append, never link"
        self.loads.append(path)
        if self.fail_load:
            raise RuntimeError("corrupt library")
        data_from = SimpleNamespace(collections=list(self._lib))
        data_to = SimpleNamespace(collections=[])
        yield data_from, data_to
        data_to.collections = [self._lib[n] for n in data_to.collections]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MIXAR_AGENT_CACHE_DIR", str(tmp_path))
    j = Journal(str(tmp_path / "j.sqlite"))
    bindings.reset()
    monkeypatch.setattr(document, "set_run_active", lambda f: None)
    monkeypatch.setattr(document, "document_identity", lambda scene=None, bpy=None: dict(IDENTITY))
    bindings.activate({"run_id": "r1", "session_id": "s1", "turn_epoch": 1}, journal=j,
                      identity_fn=lambda: IDENTITY)
    bindings.bind_task(
        {"run_id": "r1", "turn_epoch": 1, "task_id": "t1", "generation": 0,
         "attempt": 1, "fence_token": 0, "worker_connection_id": "p-sbx-0"},
        journal=j,
    )
    aid = str(uuid.uuid4())
    data = b"BLENDER" + os.urandom(64)
    with open(os.path.join(paths.staging_dir("inst"), f"{aid}.blend"), "wb") as f:
        f.write(data)
    yield SimpleNamespace(journal=j, aid=aid, hash=hashlib.sha256(data).hexdigest(), bpy=FakeBpy())
    j.close()
    bindings.reset()


def _params(env, **over):
    p = {
        "run_id": "r1", "turn_epoch": 1, "task_id": "t1", "generation": 0, "fence_token": 0,
        "operation_id": "op-1", "payload_hash": "ph-1", "op": "append_collection",
        "artifact_id": env.aid, "content_hash": env.hash, "collection_name": "wc_task1",
        "object_names": ["Cube", "Cube.001"], "target_collection": "Mixie Agent",
    }
    p.update(over)
    return p


def test_applied_receipt_and_selection_preserved(env):
    out = commit.append_collection(_params(env), bpy_module=env.bpy, journal=env.journal)
    assert out["success"] and out["state"] == "applied"
    r = out["receipt"]
    assert r["created_object_names"] == ["Cube", "Cube.001"]
    assert r["collection_name"] == "wc_task1" and r["target_collection"] == "Mixie Agent"
    assert "document_epoch" in r and "applied_at" in r
    target = env.bpy.context.scene.collection.children.get("Mixie Agent")
    assert target is not None and target.children.get("wc_task1") is not None
    assert env.bpy.context.view_layer.objects.active is env.bpy.user[0]
    assert env.bpy.user[0].selected is True
    assert env.journal.op_get("op-1")["state"] == APPLIED


def test_idempotent_replay_and_payload_mismatch(env):
    first = commit.append_collection(_params(env), bpy_module=env.bpy, journal=env.journal)
    again = commit.append_collection(_params(env), bpy_module=env.bpy, journal=env.journal)
    assert again["replayed"] is True and again["receipt"] == first["receipt"]
    assert len(env.bpy.loads) == 1  # not re-executed
    bad = commit.append_collection(_params(env, payload_hash="other"), bpy_module=env.bpy, journal=env.journal)
    assert bad["error_type"] == "payload_mismatch"


def test_stale_epoch_fence_and_unknown_run(env):
    assert commit.append_collection(_params(env, turn_epoch=0), bpy_module=env.bpy, journal=env.journal)["error_type"] == "stale_epoch"
    assert commit.append_collection(_params(env, run_id="zz"), bpy_module=env.bpy, journal=env.journal)["error_type"] == "unknown_run"
    bindings.bind_task({"run_id": "r1", "turn_epoch": 1, "task_id": "t1", "generation": 0,
                        "attempt": 2, "fence_token": 9}, journal=env.journal)
    assert commit.append_collection(_params(env, fence_token=8), bpy_module=env.bpy, journal=env.journal)["error_type"] == "stale_fence"
    assert commit.append_collection(_params(env, fence_token=9), bpy_module=env.bpy, journal=env.journal)["success"]
    assert env.bpy.loads == [os.path.join(paths.staging_dir("inst"), f"{env.aid}.blend")]


def test_artifact_missing_and_hash_mismatch(env):
    missing = commit.append_collection(_params(env, artifact_id=str(uuid.uuid4())), bpy_module=env.bpy, journal=env.journal)
    assert missing["error_type"] == "artifact_missing"
    bad = commit.append_collection(_params(env, content_hash="0" * 64), bpy_module=env.bpy, journal=env.journal)
    assert bad["error_type"] == "hash_mismatch"
    absent = commit.append_collection(_params(env, collection_name="nope"), bpy_module=env.bpy, journal=env.journal)
    assert absent["error_type"] == "artifact_missing"
    # A refused-before-publish op is left PREPARED, never UNKNOWN.
    assert env.journal.op_get("op-1")["state"] == "prepared"


def test_deferred_during_paint_or_locked_interface(env):
    env.bpy.context.mode = "PAINT_TEXTURE"
    out = commit.append_collection(_params(env), bpy_module=env.bpy, journal=env.journal)
    assert out["error_type"] == "deferred" and env.bpy.loads == []
    env.bpy.context.mode = "OBJECT"
    env.bpy.context.window_manager.is_interface_locked = True
    assert commit.append_collection(_params(env), bpy_module=env.bpy, journal=env.journal)["error_type"] == "deferred"
    env.bpy.context.window_manager.is_interface_locked = False
    env.bpy.context.mode = "EDIT_MESH"  # edit mode is fine
    assert commit.append_collection(_params(env), bpy_module=env.bpy, journal=env.journal)["success"]


def test_mid_publish_failure_is_unknown_not_replayed(env):
    env.bpy.fail_load = True
    out = commit.append_collection(_params(env), bpy_module=env.bpy, journal=env.journal)
    assert out["error_type"] == "unknown" and out["state"] == "unknown"
    assert env.journal.op_get("op-1")["state"] == "unknown"
    env.bpy.fail_load = False
    again = commit.append_collection(_params(env), bpy_module=env.bpy, journal=env.journal)
    assert again["error_type"] == "unknown"  # inspect/reconcile, never blind replay


def test_invalid_params(env):
    assert commit.append_collection(_params(env, op="replace"), bpy_module=env.bpy, journal=env.journal)["error_type"] == "invalid_params"
    assert commit.append_collection({"run_id": "r1"}, bpy_module=env.bpy, journal=env.journal)["error_type"] == "invalid_params"


def test_missing_client_instance_id_refuses_with_a_typed_error(env):
    """With no instance id there is no staging root to name; the refusal must
    stay inside the typed error path instead of escaping as a ValueError."""
    env.bpy.context.window_manager.mixie_instance_id = ""
    out = commit.append_collection(_params(env), bpy_module=env.bpy, journal=env.journal)
    assert out["success"] is False and out["error_type"] == "invalid_params"
    assert env.bpy.loads == [] and env.journal.op_get("op-1") is None


def test_missing_content_hash_is_invalid_params(env):
    out = commit.append_collection(_params(env, content_hash=""), bpy_module=env.bpy, journal=env.journal)
    assert out["error_type"] == "invalid_params" and env.bpy.loads == []
    absent = commit.append_collection(_params(env, artifact_id=""), bpy_module=env.bpy, journal=env.journal)
    assert absent["error_type"] == "invalid_params"


def test_superseded_op_is_not_replayed(env):
    from mixar.modules.common.agent_execution.journal import SUPERSEDED
    env.journal.op_prepare(
        "op-1", run_id="r1", task_id="t1", generation=0, fence=0,
        payload_hash="ph-1", document_id="doc", document_epoch=1, artifact_id=env.aid,
    )
    env.journal.op_set_state("op-1", SUPERSEDED)
    out = commit.append_collection(_params(env), bpy_module=env.bpy, journal=env.journal)
    assert out["success"] is False and out["error_type"] == "unknown"
    assert out["state"] == SUPERSEDED and env.bpy.loads == []
    assert env.journal.op_get("op-1")["state"] == SUPERSEDED


def test_stale_document_refuses_publish(env, monkeypatch):
    monkeypatch.setattr(
        document, "document_identity",
        lambda scene=None, bpy=None: {
            "document_id": "other-doc", "document_epoch": 1, "scene_id": "sc", "scene_name": "Scene",
        },
    )
    out = commit.append_collection(_params(env), bpy_module=env.bpy, journal=env.journal)
    assert out["error_type"] == "stale_document" and env.bpy.loads == []
    assert env.journal.op_get("op-1") is None


def test_activation_retry_and_commit_agree_after_undo(env, monkeypatch):
    monkeypatch.setattr(document, "document_identity",
                        lambda **_: dict(IDENTITY, document_epoch=2))
    activation = bindings.activate(
        {"run_id": "r1", "session_id": "s1", "turn_epoch": 1}, journal=env.journal,
    )
    publish = commit.append_collection(_params(env), bpy_module=env.bpy, journal=env.journal)
    assert activation["success"] is False and publish["success"] is False
    assert activation["error_type"] == publish["error_type"] == "stale_epoch"
    assert env.bpy.loads == [] and env.journal.op_get("op-1") is None


def test_in_process_running_stays_deferred(env):
    from mixar.modules.common.agent_execution.journal import RUNNING
    env.journal.op_prepare(
        "op-1", run_id="r1", task_id="t1", generation=0, fence=0,
        payload_hash="ph-1", document_id="doc", document_epoch=1, artifact_id=env.aid,
    )
    env.journal.op_set_state("op-1", RUNNING)
    out = commit.append_collection(_params(env), bpy_module=env.bpy, journal=env.journal)
    assert out["error_type"] == "deferred" and out["state"] == RUNNING
    assert env.bpy.loads == []


# --- placement (scene-from-reference) ---------------------------------------

class _Euler:
    def __init__(self, z=0.0):
        self.x, self.y, self.z = 0.0, 0.0, z


class PlacedObj(FakeObj):
    def __init__(self, name, location=(0.0, 0.0, 0.0), parent=None):
        super().__init__(name)
        self.location = tuple(location)
        self.rotation_euler = _Euler()
        self.scale = (1.0, 1.0, 1.0)
        self.parent = parent


def _placed_env(env):
    root = PlacedObj("Root", (1.0, 0.0, 0.5))
    child = PlacedObj("Leg", (0.2, 0.2, 0.0), parent=root)
    stray = PlacedObj("Stray", (0.0, 1.0, 0.0))
    env.bpy._lib = {"wc_task1": FakeCollection("wc_task1", [root, child, stray])}
    return root, child, stray


def _approx(a, b):
    return all(abs(float(x) - float(y)) < 1e-9 for x, y in zip(a, b))


def test_placement_translate_only(env):
    root, child, stray = _placed_env(env)
    out = commit.append_collection(_params(env, placement={"location": [3, 4, 0]}),
                                   bpy_module=env.bpy, journal=env.journal)
    assert out["success"] and out["receipt"]["placement_applied"] is True
    assert out["receipt"]["placement"] == {"location": [3.0, 4.0, 0.0], "rotation_z_deg": 0.0, "scale": 1.0}
    assert _approx(root.location, (4.0, 4.0, 0.5)) and _approx(stray.location, (3.0, 5.0, 0.0))
    assert _approx(child.location, (0.2, 0.2, 0.0))          # child untouched
    assert root.scale == (1.0, 1.0, 1.0) and root.rotation_euler.z == 0.0


def test_placement_rotate_90_moves_x_to_y(env):
    root, child, stray = _placed_env(env)
    commit.append_collection(_params(env, placement={"rotation_z_deg": 90}),
                             bpy_module=env.bpy, journal=env.journal)
    assert _approx(root.location, (0.0, 1.0, 0.5))
    assert abs(root.rotation_euler.z - 1.5707963267948966) < 1e-9
    assert _approx(child.location, (0.2, 0.2, 0.0)) and child.rotation_euler.z == 0.0


def test_placement_scale_2_doubles_location_and_scale(env):
    root, child, stray = _placed_env(env)
    commit.append_collection(_params(env, placement={"scale": 2}), bpy_module=env.bpy, journal=env.journal)
    assert _approx(root.location, (2.0, 0.0, 1.0)) and root.scale == (2.0, 2.0, 2.0)
    assert _approx(stray.location, (0.0, 2.0, 0.0))
    assert child.scale == (1.0, 1.0, 1.0) and _approx(child.location, (0.2, 0.2, 0.0))


def test_placement_combined_order_scale_rotate_translate(env):
    root, child, stray = _placed_env(env)
    commit.append_collection(_params(env, placement={"location": [10, 0, 0], "rotation_z_deg": 90, "scale": 2}),
                             bpy_module=env.bpy, journal=env.journal)
    # (1,0,0.5) → scale 2 → (2,0,1) → rotate 90° → (0,2,1) → translate → (10,2,1)
    assert _approx(root.location, (10.0, 2.0, 1.0))


def test_invalid_placement_refused_before_append(env):
    _placed_env(env)
    for bad in ({"location": [1, 2]}, {"scale": 0}, {"scale": 1000}, {"location": [1e9, 0, 0]},
                {"rotation_z_deg": "ninety"}, {"location": [float("nan"), 0, 0]}, "north"):
        out = commit.append_collection(_params(env, placement=bad), bpy_module=env.bpy, journal=env.journal)
        assert out["error_type"] == "invalid_params", bad
    assert env.bpy.loads == []                          # nothing was appended
    assert env.journal.op_get("op-1") is None           # nothing was journaled


def test_placement_replay_returns_recorded_receipt_without_reapplying(env):
    root, child, stray = _placed_env(env)
    p = _params(env, placement={"location": [3, 0, 0]})
    first = commit.append_collection(p, bpy_module=env.bpy, journal=env.journal)
    again = commit.append_collection(p, bpy_module=env.bpy, journal=env.journal)
    assert again["replayed"] is True and again["receipt"] == first["receipt"]
    assert _approx(root.location, (4.0, 0.0, 0.5))      # applied exactly once
    assert len(env.bpy.loads) == 1


def test_identity_placement_reports_not_applied(env):
    _placed_env(env)
    out = commit.append_collection(_params(env, placement={}), bpy_module=env.bpy, journal=env.journal)
    assert out["success"] and out["receipt"]["placement_applied"] is False
    none = commit.append_collection(_params(env, operation_id="op-2", payload_hash="ph-2"),
                                    bpy_module=env.bpy, journal=env.journal)
    assert none["receipt"]["placement"] is None and none["receipt"]["placement_applied"] is False
