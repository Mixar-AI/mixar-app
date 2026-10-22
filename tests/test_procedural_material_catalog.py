# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Procedural-material catalog lifecycle (server_catalog) and the agent's
material summary: a user who logs in after launch still gets the backend
library, and ``ready`` counts the disk cache."""

import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock  # noqa: E402

install_bpy_mock()

from mixar.modules.paint.procedural_materials import (  # noqa: E402
    material_registry as MR,
    server_catalog as SC,
)
from mixar.modules.paint.core.agent_tools import material_library as ML  # noqa: E402


@pytest.fixture
def catalog(monkeypatch, tmp_path):
    """Registry + catalog state reset; fetch thread and timer captured."""
    MR._registry.clear()
    SC.reset_server_catalog()
    token = {"value": ""}
    started = []
    monkeypatch.setattr(MR, "_get_auth_token", lambda: token["value"])
    monkeypatch.setattr(MR, "_get_base_url", lambda: "https://api.example")
    monkeypatch.setattr(MR, "_get_cache_dir", lambda: str(tmp_path))
    monkeypatch.setattr(MR, "_load_local_matgen", lambda: None)
    monkeypatch.setattr(MR, "load_matgen_materials", lambda: None)

    class _Thread:
        def __init__(self, target, daemon):
            self.target = target

        def start(self):
            started.append(self.target)

    monkeypatch.setattr(SC.threading, "Thread", _Thread)
    monkeypatch.setattr(SC.bpy.app.timers, "register", lambda *a, **k: None, raising=False)
    yield SimpleNamespace(token=token, started=started, cache=tmp_path)
    MR._registry.clear()
    SC.reset_server_catalog()


def _server_item(material_id="rust_01", name="Rust"):
    return {"material_id": material_id, "name": name, "category": "metal"}


def test_ensure_fetches_once_and_leaves_auth_to_the_worker(catalog):
    assert SC.ensure_server_catalog() == SC.LOADING
    assert len(catalog.started) == 1
    catalog.token["value"] = "tok"
    assert SC.ensure_server_catalog() == SC.LOADING
    assert SC.ensure_server_catalog() == SC.LOADING  # idempotent while loading
    assert len(catalog.started) == 1

    SC._apply_result({"ok": True, "materials": [_server_item()]})
    assert SC.catalog_status() == SC.LOADED
    assert MR.get_material("rust_01") is not None
    assert SC.ensure_server_catalog() == SC.LOADED
    assert len(catalog.started) == 1


def test_failed_fetch_is_retried_by_the_next_ensure(catalog):
    catalog.token["value"] = "tok"
    SC.ensure_server_catalog()
    SC._apply_result({"ok": False, "error": "boom"})
    assert SC.catalog_status() == SC.FAILED
    assert SC.ensure_server_catalog() == SC.LOADING
    assert len(catalog.started) == 2


def test_login_during_a_tokenless_startup_fetch_retries_once_it_fails(catalog):
    """UI register starts the fetch before login; the login hook's ensure lands
    while it is still loading. Its "not authenticated" failure must retry."""
    SC.load_server_catalog()  # paint UI register, no token yet
    assert SC.catalog_status() == SC.LOADING
    catalog.token["value"] = "tok"  # login lands
    SC.ensure_server_catalog()
    assert len(catalog.started) == 1

    SC._apply_result({"ok": False, "error": "not authenticated"})
    assert SC.catalog_status() == SC.LOADING
    assert len(catalog.started) == 2


def test_unloading_the_registry_resets_the_catalog_state(catalog):
    catalog.token["value"] = "tok"
    SC.ensure_server_catalog()
    SC._apply_result({"ok": True, "materials": [_server_item()]})
    MR.unload_all_materials()
    assert SC.catalog_status() == SC.IDLE
    assert SC.ensure_server_catalog() == SC.LOADING


def test_agent_tool_fetches_the_catalog_when_no_server_items(catalog):
    catalog.token["value"] = "tok"
    # Local materials alone (a generated one, a script-only layered-build one)
    # must not satisfy the guard.
    MR.register_material(MR.ProceduralMaterial(
        material_id="mine", name="Mine", category="ai",
        script_path=str(catalog.cache / "mine.py"),
    ))
    MR.register_material(MR.ProceduralMaterial(
        material_id="detail", name="Detail", category="layered_material", script="# s",
    ))
    result = ML.list_procedural_materials()
    assert result["catalog_status"] == SC.LOADING
    assert len(catalog.started) == 1

    SC._apply_result({"ok": True, "materials": [_server_item()]})
    result = ML.list_procedural_materials()
    assert result["catalog_status"] == SC.LOADED
    assert len(catalog.started) == 1
    assert {m["material_id"] for m in result["materials"]} == {"mine", "detail", "rust_01"}
    assert {m["material_id"]: m["source"] for m in result["materials"]} == {
        "mine": "local", "detail": "local", "rust_01": "server",
    }


def test_summary_counts_the_disk_cache_and_marks_server_items_downloadable(catalog, monkeypatch):
    monkeypatch.setattr(ML.bpy.data.node_groups, "get", lambda name: None, raising=False)
    cached = MR.ProceduralMaterial(material_id="cached", name="Cached", category="metal")
    uncached = MR.ProceduralMaterial(material_id="uncached", name="Uncached", category="metal")
    cached.source = uncached.source = SC.SERVER_SOURCE
    # A layered-build material carries script text only: local, not server.
    script_only = MR.ProceduralMaterial(
        material_id="detail", name="Detail", category="layered_material", script="# s",
    )
    (catalog.cache / "cached.py").write_text("# script", encoding="utf-8")
    missing_local = MR.ProceduralMaterial(
        material_id="gone", name="Gone", category="ai",
        script_path=str(catalog.cache / "missing.py"),
    )

    summary = ML._material_summary(cached)
    assert summary["ready"] is True
    assert summary["source"] == "server" and summary["downloadable"] is True

    summary = ML._material_summary(uncached)
    assert summary["ready"] is False
    assert summary["source"] == "server" and summary["downloadable"] is True

    summary = ML._material_summary(script_only)
    assert summary["ready"] is True
    assert summary["source"] == "local" and summary["downloadable"] is False

    summary = ML._material_summary(missing_local)
    assert summary["ready"] is False
    assert summary["source"] == "local" and summary["downloadable"] is False


def test_login_hook_marshals_the_catalog_fetch_to_the_main_thread(monkeypatch):
    from mixar.modules.auth.core import auth_hooks

    # Exercise material-hook wiring without starting unrelated authenticated
    # generation/sound requests from this standalone test.
    for name, function in (
        ("mixar.bootstrap.generation_catalog_cache", "refresh_generation_catalog_cache"),
        ("mixar.bootstrap.chat_generate_options_cache", "refresh_chat_generate_options_cache"),
        ("mixar.modules.space_mixie_chat.core.sound_catalog", "refresh_async"),
    ):
        stub = SimpleNamespace(**{function: lambda: None})
        monkeypatch.setitem(sys.modules, name, stub)
        parent_name, _, child = name.rpartition(".")
        if parent_name in sys.modules:
            monkeypatch.setattr(sys.modules[parent_name], child, stub, raising=False)

    registered = []
    monkeypatch.setattr(
        auth_hooks, "logger", SimpleNamespace(warning=lambda *_a, **_k: None)
    )
    import bpy

    monkeypatch.setattr(
        bpy.app.timers, "register",
        lambda fn, first_interval=None: registered.append((fn, first_interval)),
        raising=False,
    )
    auth_hooks.refresh_generation_caches()
    assert (auth_hooks._ensure_material_catalog, 0) in registered

    calls = []
    monkeypatch.setattr(SC, "ensure_server_catalog", lambda: calls.append(1) or SC.LOADING)
    assert auth_hooks._ensure_material_catalog() is None  # one-shot timer
    assert calls == [1]


@pytest.fixture
def threaded_catalog(monkeypatch, tmp_path):
    """Real workers and queued results; credentials block until released.

    All token/transport bytes are synthetic. The caller manually runs captured
    timers, as Blender's main loop would, and every worker is joined at teardown.
    """
    from mixar.modules.paint.procedural_materials import matgen_client

    MR._registry.clear()
    SC.reset_server_catalog()
    caller = threading.current_thread()
    entered, release = threading.Event(), threading.Event()
    threads, reads, fetches, timers, errors = [], [], [], [], []
    token = {"value": "synthetic-token"}
    real_thread = threading.Thread

    def read_token():
        assert threading.current_thread() is not caller, "Credential read on caller thread"
        value = token["value"]  # a login during this read affects only the retry
        reads.append(threading.current_thread())
        entered.set()
        assert release.wait(3), "Test did not release the synthetic credential read"
        return value

    def fetch(_token, _url, result_queue):
        assert threading.current_thread() is not caller
        fetches.append(threading.current_thread())
        result_queue.put({"ok": True, "materials": [_server_item()]})

    def thread(*, target, daemon):
        def run():
            try:
                target()
            except BaseException as exc:
                errors.append(exc)
        worker = real_thread(target=run, daemon=daemon)
        threads.append(worker)
        return worker

    def register_timer(callback, **_kwargs):
        assert threading.current_thread() is caller
        timers.append(callback)

    class MainThreadBpy:
        def __getattr__(self, name):
            assert threading.current_thread() is caller, "Worker touched bpy"
            return getattr(original_bpy, name)

    original_bpy = SC.bpy
    monkeypatch.setattr(SC, "bpy", MainThreadBpy())
    monkeypatch.setattr(SC, "threading", SimpleNamespace(Thread=thread))
    monkeypatch.setattr(original_bpy.app.timers, "register", register_timer, raising=False)
    monkeypatch.setattr(original_bpy.types.WindowManager, "mixar_matgen_status", "", raising=False)
    monkeypatch.setattr(MR, "_get_auth_token", read_token)
    monkeypatch.setattr(MR, "_get_base_url", lambda: "https://catalog.invalid")
    monkeypatch.setattr(MR, "_get_cache_dir", lambda: str(tmp_path))
    monkeypatch.setattr(MR, "_load_local_matgen", lambda: None)
    monkeypatch.setattr(MR, "load_matgen_materials", lambda: None)
    monkeypatch.setattr(matgen_client, "fetch_catalog_async", fetch)

    def finish_worker():
        release.set()
        threads[-1].join(timeout=3)
        assert not threads[-1].is_alive()
        assert not errors

    def poll():
        assert timers, "Expected a pending main-thread catalog callback"
        assert timers.pop(0)() is None  # completed result retires this timer

    yield SimpleNamespace(token=token, entered=entered, release=release, threads=threads,
                          reads=reads, fetches=fetches, timers=timers,
                          finish_worker=finish_worker, poll=poll)
    release.set()
    for worker in threads:
        worker.join(timeout=3)
        assert not worker.is_alive()
    MR._registry.clear()
    SC.reset_server_catalog()
    assert not errors


@pytest.mark.parametrize("entry", ["ensure", "auth_hook", "agent_list", "retry"])
def test_catalog_entry_points_return_while_worker_credentials_are_blocked(threaded_catalog, entry):
    from mixar.modules.auth.core import auth_hooks

    state = threaded_catalog
    if entry == "retry":
        SC._state["status"] = SC.FAILED
    if entry == "auth_hook":
        assert auth_hooks._ensure_material_catalog() is None
    elif entry == "agent_list":
        assert ML.list_procedural_materials()["catalog_status"] == SC.LOADING
    else:
        assert SC.ensure_server_catalog() == SC.LOADING
    # Reaching this assertion before release proves the caller did not wait
    # for credentials; no fragile millisecond wall-clock threshold is needed.
    assert state.entered.wait(2)
    assert not state.release.is_set()
    assert SC.catalog_status() == SC.LOADING
    for _ in range(10):
        assert SC.ensure_server_catalog() == SC.LOADING
        assert auth_hooks._ensure_material_catalog() is None
        assert ML.list_procedural_materials()["catalog_status"] == SC.LOADING
    assert len(state.threads) == len(state.reads) == 1
    state.finish_worker()
    state.poll()
    assert SC.catalog_status() == SC.LOADED
    assert MR.get_material("rust_01") is not None
    assert SC.ensure_server_catalog() == SC.LOADED
    assert len(state.threads) == len(state.fetches) == 1
    assert not state.timers


def test_tokenless_worker_fails_without_network_or_automatic_retry(threaded_catalog):
    state = threaded_catalog
    state.token["value"] = ""
    assert SC.ensure_server_catalog() == SC.LOADING
    assert state.entered.wait(2)
    state.finish_worker()
    state.poll()
    assert SC.catalog_status() == SC.FAILED
    assert not state.fetches and not state.timers
    assert len(state.threads) == 1
    assert SC._state["retry"] is False

    # An explicit later call can recover after login.
    state.entered.clear()
    state.release.clear()
    state.token["value"] = "synthetic-token"
    assert SC.ensure_server_catalog() == SC.LOADING
    assert state.entered.wait(2)
    state.finish_worker()
    state.poll()
    assert SC.catalog_status() == SC.LOADED
    assert len(state.threads) == 2 and len(state.fetches) == 1


@pytest.mark.parametrize("logged_in", [False, True])
def test_pending_login_retry_is_coalesced_and_cannot_spin(threaded_catalog, logged_in):
    from mixar.modules.auth.core import auth_hooks

    state = threaded_catalog
    state.token["value"] = ""
    SC.load_server_catalog()  # startup before login
    assert state.entered.wait(2)
    state.token["value"] = "synthetic-token" if logged_in else ""
    for _ in range(10):
        auth_hooks._ensure_material_catalog()
    assert len(state.threads) == 1
    state.finish_worker()
    state.entered.clear()
    state.release.clear()
    state.poll()  # queued failure starts exactly one retry on another worker
    assert state.entered.wait(2)
    assert not state.release.is_set()
    assert SC.catalog_status() == SC.LOADING
    assert len(state.threads) == len(state.reads) == 2
    state.finish_worker()
    state.poll()
    assert SC.catalog_status() == (SC.LOADED if logged_in else SC.FAILED)
    assert len(state.fetches) == int(logged_in)
    assert len(state.threads) == 2
    assert not state.timers
    assert SC._state["retry"] is False
