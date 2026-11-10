# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Remix: lineage, the web → desktop inbox, source download and the publish hooks."""

import hashlib
import io
import json
import os
import plistlib
import stat
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace as NS

import pytest

from mixar.modules.game_studio.core import pipeline
from mixar.modules.game_studio.core.jobs import JobError
from mixar.modules.game_studio.core.store_client import StoreError
from mixar.modules.remix.constants import POLL_FAST_S, POLL_SLOW_S, REMIX_PROP
from mixar.modules.remix.core import inbox as inbox_mod
from mixar.modules.remix.core import intake, lineage, opening, source_job
from mixar.modules.remix.core.client import RemixClient

ORIGIN = {"kind": "game", "id": "11111111-1111-1111-1111-111111111111", "slug": "ash-glaive",
          "title": "Ash Glaive", "author": {"handle": "alice", "display_name": "Alice"},
          "url": "https://play.example/games/ash-glaive", "extra": "dropped"}
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class Chat(list):
    """Stands in for the chat CollectionProperty (``clear()``)."""


class Scene(dict):
    """ID properties as a dict, plus the registered ``mixie_*`` properties."""

    def __init__(self, name="Scene"):
        super().__init__()
        self.name = name
        self.mixie_session_id = "session-123"
        self.mixie_chat_user_id = "user-9"
        self.mixie_chat_messages = Chat(["how do I rig this", "secret client brief"])
        self.unrelated = "kept"
        self.bl_rna = NS(properties=[NS(identifier=n) for n in (
            "rna_type", "mixie_session_id", "mixie_chat_user_id", "mixie_chat_messages", "unrelated")])
        self.mixar_web_publish = NS(
            published_scene_id="scene-1", slug="my-slug", unset=[],
            bl_rna=NS(properties=[NS(identifier=n) for n in ("rna_type", "published_scene_id", "slug")]))
        self.mixar_web_publish.property_unset = self.mixar_web_publish.unset.append

    def property_unset(self, name):
        setattr(self, name, "")


# --- lineage ------------------------------------------------------------------

def test_stamp_round_trips_and_drops_unknown_keys():
    scene = Scene()
    stored = lineage.stamp(scene, ORIGIN)
    assert "extra" not in stored and json.loads(scene[REMIX_PROP]) == stored
    assert lineage.origin_of(scene)["author"] == {"handle": "alice", "display_name": "Alice"}
    assert lineage.credit_line(lineage.origin_of(scene)) == "Remixed from Ash Glaive by @alice"
    lineage.clear(scene)
    assert lineage.origin_of(scene) is None


@pytest.mark.parametrize("junk", [None, {}, {"kind": "video", "id": "x"}, {"kind": "game"}, "text"])
def test_unusable_origins_are_refused(junk):
    scene = Scene()
    assert lineage.stamp(scene, junk) is None and REMIX_PROP not in scene
    scene[REMIX_PROP] = "not json"
    assert lineage.origin_of(scene) is None


def test_lineage_fields_keep_posts_and_games_apart():
    assert lineage.game_fields(ORIGIN) == {"remixed_from_id": ORIGIN["id"]}
    assert lineage.post_fields(ORIGIN) == {}
    post = dict(ORIGIN, kind="post", slug=None)
    assert lineage.post_fields(post) == {"remixed_from_id": ORIGIN["id"]}
    assert lineage.game_fields(post) == {} and lineage.game_fields(None) == {}


def test_remix_title_is_distinct_bounded_and_stable():
    assert lineage.remix_title("Ash Glaive") == "Ash Glaive (remix)"
    assert lineage.remix_title("Ash Glaive (remix)") == "Ash Glaive (remix)"
    long = lineage.remix_title("x" * 200, 80)
    assert len(long) == 80 and long.endswith(" (remix)")
    assert lineage.remix_title("") == "Untitled (remix)"


def test_scrub_removes_the_creators_conversation_and_identity_only():
    scene = Scene()
    scene["mixar_game_store"] = json.dumps({"game_id": "theirs"})
    scene["mixar_game_role_stuff"] = "kept"
    lineage.stamp(scene, ORIGIN)
    cleared = lineage.scrub(scene)
    assert scene.mixie_chat_messages == [] and scene.mixie_session_id == "" and scene.mixie_chat_user_id == ""
    assert "mixar_game_store" not in scene and set(scene.mixar_web_publish.unset) == {"published_scene_id", "slug"}
    assert {"mixar_game_store", "mixie_chat_messages", "mixar_web_publish"} <= set(cleared)
    # Untouched: other data, and the lineage (a remix of a remix still names its parent).
    assert scene.unrelated == "kept" and scene["mixar_game_role_stuff"] == "kept"
    assert lineage.origin_of(scene)["id"] == ORIGIN["id"]


class Stored(dict):
    """Blender's system-property storage for one ID."""


def background_scene():
    """A scene as a BACKGROUND Mixar sees it: no chat property is registered,
    but the saved values are still in the file's system properties."""
    scene = dict()
    stored = Stored({"mixie_chat_messages": [{"text": "secret client brief"}], "mixie_session_id": "s-1",
                     "mixie_chat_password": "", "mixie_moodboard_images": [1], "mixar_web_publish": {"slug": "x"},
                     "mixar_op_history_id": "log-7", "cycles": {"samples": 64}, "mixar_zen_sky": {"on": True}})
    holder = type("BackgroundScene", (dict,), {"bl_system_properties_get": lambda self: stored})(scene)
    holder.stored = stored
    return holder


def test_scrub_reaches_stored_values_when_no_property_is_registered():
    scene = background_scene()
    scene["mixar_game_store"] = "{}"
    scene["mixie_ws_resume"] = "cursor-of-the-creators-agent-session"
    scene["mixar_game_spec"] = "{}"
    lineage.stamp(scene, ORIGIN)
    assert lineage.private_keys(scene) == [
        "mixar_game_store", "mixar_op_history_id", "mixar_web_publish", "mixie_chat_messages",
        "mixie_chat_password", "mixie_moodboard_images", "mixie_session_id", "mixie_ws_resume"]
    cleared = lineage.scrub(scene)
    assert lineage.private_keys(scene) == [] and "mixie_chat_messages" in cleared
    # Render and look settings are not private and stay; so do the game's own settings.
    assert set(scene.stored) == {"cycles", "mixar_zen_sky"}
    assert set(scene) == {"mixar_game_spec", REMIX_PROP} and lineage.origin_of(scene)["id"] == ORIGIN["id"]


class Block(dict):
    """A datablock with ordinary custom properties and (optionally) stored values."""

    def __init__(self, name, custom=(), stored=None):
        super().__init__(custom)
        self.name, self.stored = name, stored

    def as_pointer(self):
        return id(self)

    def bl_system_properties_get(self):
        return self.stored


class Data:
    """bpy.data, reduced: named collections that iterate and have ``keys``."""

    def __init__(self, **collections):
        for name, items in collections.items():
            setattr(self, name, _Coll(items))


class _Coll(list):
    def keys(self):
        return [item.name for item in self]


def test_every_datablock_is_swept_not_just_scenes():
    hero = Block("Hero", {"mixar_game_role": "player", "mixar_rig_job_id": "job-on-the-creators-account",
                          "mixar_workspace_token": "a" * 64})
    lane = Block("Lane", {"mixar_workspace_state": "committed", "mixar_workspace_merge_plan": "{}"})
    wm = Block("WinMan", stored=Stored({"mixie_chat_history_entries": [{"name": "Secret client chat"}],
                                        "mixie_instance_id": "i-1", "mixar_addon_projects_dir": "/Users/x"}))
    scene = Block("Scene", {"mixar_scene_id": "s-1", "mixar_game_spec": "{}"}, Stored({"cycles": {}}))
    data = Data(scenes=[scene], objects=[hero], collections=[lane], window_managers=[wm], futures=[Block("New")])
    assert len(lineage.all_ids(data)) == 5  # a data type nobody listed is still found
    assert set(lineage.leftovers(data)) == {"Block:Hero", "Block:Lane", "Block:WinMan", "Block:Scene"}
    assert lineage.scrub_file(data) == 7
    assert lineage.leftovers(data) == {}
    # What makes it a game stays; so does a path-like setting that is not Mixie's.
    assert dict(hero) == {"mixar_game_role": "player"} and dict(scene) == {"mixar_game_spec": "{}"}
    assert set(wm.stored) == {"mixar_addon_projects_dir"}


def test_a_remix_never_takes_its_parents_slug():
    first = lineage.remix_slug("ash-glaive-remix", "a1b2c3d4")
    assert first == "ash-glaive-remix-a1b2c3" and first != lineage.remix_slug("ash-glaive-remix", "ffff0000")
    assert len(lineage.remix_slug("x" * 80, "abcdef12")) <= 48
    assert lineage.remix_slug("", "!!") == "remix-x"


def test_ids_without_system_storage_are_left_alone():
    assert lineage.scrub_stored(NS(name="old-blender-object")) == []
    assert lineage.private_keys(NS()) == []


# --- inbox ----------------------------------------------------------------------

def test_inbox_polls_fast_after_start_then_slow():
    now = [0.0]
    box = inbox_mod.Inbox(clock=lambda: now[0])
    assert box.interval() == POLL_FAST_S
    now[0] = 181.0
    assert box.interval() == POLL_SLOW_S


def test_inbox_announces_each_remix_once_and_survives_failures():
    box, said = inbox_mod.Inbox(), []
    answers = [[{"intent_id": "a", "origin": ORIGIN}], RuntimeError("offline"),
               [{"intent_id": "a", "origin": ORIGIN}, {"intent_id": "b", "origin": ORIGIN}, {"junk": 1}]]

    def client():
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return NS(pending=lambda: answer)

    assert [i["intent_id"] for i in inbox_mod.fetch_once(box, client, said.append)] == ["a"]
    assert inbox_mod.fetch_once(box, client, said.append) == [] and box.count() == 1  # kept
    assert [i["intent_id"] for i in inbox_mod.fetch_once(box, client, said.append)] == ["b"]
    assert [i["intent_id"] for i in said] == ["a", "b"] and box.newest()["intent_id"] == "a"
    assert box.take("a")["intent_id"] == "a" and box.take("a") is None and box.count() == 1


def test_inbox_backs_off_while_signed_out_and_recovers():
    from mixar.modules.remix.constants import POLL_SIGNED_OUT_S
    box = inbox_mod.Inbox()

    def signed_out():
        raise StoreError("Sign in to Mixar to publish.", "login_required", 401)

    inbox_mod.fetch_once(box, signed_out, lambda item: None)
    assert box.interval() == POLL_SIGNED_OUT_S
    inbox_mod.fetch_once(box, lambda: NS(pending=lambda: []), lambda item: None)
    assert box.interval() == POLL_FAST_S


def test_inbox_never_runs_two_fetches_at_once():
    box = inbox_mod.Inbox()
    assert box.begin_fetch() is True and box.begin_fetch() is False
    box.end_fetch(None)
    assert box.begin_fetch() is True


# --- client + intake against a stub store ---------------------------------------

MIXAR_BYTES = b"BLENDER fake project " * 64


def package_zip(extra=None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("mixar_export/scene.glb", b"glTF")
        archive.writestr("mixar_export/game_spec.json", json.dumps({"nodes": []}))
        for name, body in (extra or {}).items():
            info = zipfile.ZipInfo(name)
            if body is None:
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, "/etc/passwd")
            else:
                archive.writestr(info, body)
    return buffer.getvalue()


class _Stub(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _handle(self):
        self.server.calls.append((self.command, self.path, self.headers.get("Authorization")))
        status, body = self.server.routes.get((self.command, self.path), (404, {"detail": {
            "code": "not_found", "message": "No such route"}}))
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = _handle


@pytest.fixture
def store():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
    server.calls, server.routes = [], {}
    threading.Thread(target=server.serve_forever, daemon=True).start()
    server.base = f"http://127.0.0.1:{server.server_port}"
    server.client = lambda _base=None: RemixClient(server.base, token_provider=lambda: "tok",
                                                   refresh=lambda: False)
    yield server
    server.shutdown()


def serve_source(store, data: bytes, fmt: str, sha=None, size=None) -> dict:
    store.routes[("GET", "/signed/source")] = (200, data)
    return {"origin": ORIGIN, "starter_prompts": ["Change the theme"],
            "source": {"format": fmt, "url": f"{store.base}/signed/source", "filename": "x",
                       "size_bytes": len(data) if size is None else size,
                       "sha256": hashlib.sha256(data).hexdigest() if sha is None else sha}}


def test_client_reads_the_inbox_and_claims(store):
    store.routes[("GET", "/api/v1/remix/intents/pending")] = (200, {
        "status": "success", "message": "ok",
        "data": {"items": [{"intent_id": "i1", "origin": ORIGIN}, {"no_id": True}]}})
    store.routes[("POST", "/api/v1/remix/intents/i1/claim")] = (200, {
        "status": "success", "message": "ok", "data": {"origin": ORIGIN}})
    client = store.client()
    assert [i["intent_id"] for i in client.pending()] == ["i1"]
    assert client.claim("i1")["origin"]["slug"] == "ash-glaive"
    assert all(auth == "Bearer tok" for _m, _p, auth in store.calls)


def test_claim_downloads_a_mixar_source_without_the_bearer(store, tmp_path):
    package = serve_source(store, MIXAR_BYTES, "mixar")
    store.routes[("POST", "/api/v1/remix/intents/i1/claim")] = (200, {
        "status": "success", "message": "ok", "data": package})
    handle = NS(progress=lambda *a, **k: None, cancel_event=threading.Event())
    plan = intake.claim_work(str(tmp_path), store.base, "i1", store.client)(handle)
    assert plan["format"] == "mixar" and open(plan["path"], "rb").read() == MIXAR_BYTES
    # The user's project is a new file beside the download, named as a remix.
    assert os.path.basename(plan["project_path"]) == "Ash Glaive remix.mixar"
    assert os.path.dirname(plan["project_path"]) == os.path.dirname(plan["path"])
    assert plan["origin"]["id"] == ORIGIN["id"] and plan["starter_prompts"] == ["Change the theme"]
    assert ("GET", "/signed/source", None) in store.calls  # signed URL: no Authorization header


def test_download_needs_a_size_and_a_link_mixar_will_follow(store, tmp_path):
    package = serve_source(store, MIXAR_BYTES, "mixar")
    package["source"]["size_bytes"] = 0
    with pytest.raises(JobError) as no_size:
        intake.fetch_package(store.client(), package, str(tmp_path))
    assert no_size.value.code == "bad_response"
    for link in ("http://example.com/source.mixar", "ftp://127.0.0.1/x", "file:///etc/passwd"):
        package = serve_source(store, MIXAR_BYTES, "mixar")
        package["source"]["url"] = link
        with pytest.raises(JobError) as refused:
            intake.fetch_package(store.client(), package, str(tmp_path))
        assert refused.value.code == "bad_response"
    with pytest.raises(StoreError):
        store.client().source("video", "x")


def test_download_must_match_the_stores_record(store, tmp_path):
    handle = None
    bad_sha = serve_source(store, MIXAR_BYTES, "mixar", sha="0" * 64)
    with pytest.raises(JobError) as wrong:
        intake.fetch_package(store.client(), bad_sha, str(tmp_path), handle)
    assert wrong.value.code == "sha256_mismatch"
    short = serve_source(store, MIXAR_BYTES, "mixar", size=len(MIXAR_BYTES) + 5)
    with pytest.raises(JobError) as size:
        intake.fetch_package(store.client(), short, str(tmp_path), handle)
    assert size.value.code == "size_mismatch"
    # Nothing half-downloaded is left behind to be opened by mistake.
    assert not [f for _b, _d, files in os.walk(tmp_path) for f in files]


def test_game_package_is_unpacked_safely(store, tmp_path):
    plan = intake.fetch_package(store.client(), serve_source(store, package_zip(), "game_package"),
                                str(tmp_path))
    assert plan["path"].endswith("scene.glb") and plan["spec_path"].endswith("game_spec.json")
    for evil in ({"../escape.txt": b"x"}, {"link": None}):
        with pytest.raises(JobError) as refused:
            intake.fetch_package(store.client(), serve_source(store, package_zip(evil), "game_package"),
                                 str(tmp_path))
        assert refused.value.code == "unsafe_archive"


def test_unknown_formats_and_origins_are_refused(store, tmp_path):
    for package in ({"origin": ORIGIN, "source": {"format": "exe", "url": "x"}},
                    {"origin": {"kind": "nope"}, "source": {"format": "mixar", "url": "x"}}, {}):
        with pytest.raises(JobError) as refused:
            intake.fetch_package(store.client(), package, str(tmp_path))
        assert refused.value.code == "bad_response"


def test_store_refusals_reach_the_user(store, tmp_path):
    store.routes[("POST", "/api/v1/remix/intents/i1/claim")] = (403, {
        "status": "failure", "message": "The creator has turned remixing off for this",
        "data": {"code": "remix_not_allowed"}})
    handle = NS(progress=lambda *a, **k: None, cancel_event=threading.Event())
    with pytest.raises(JobError) as refused:
        intake.claim_work(str(tmp_path), store.base, "i1", store.client)(handle)
    assert refused.value.code == "remix_not_allowed" and "turned remixing off" in refused.value.message


# --- opening --------------------------------------------------------------------

def test_roles_return_to_objects_by_name():
    tagged = {}

    def set_role(obj, role, params):
        tagged[obj.name] = (role, params)
        return True, []

    objects = [NS(name="Hero"), NS(name="Coin"), NS(name="Rock")]
    spec = {"nodes": [{"name": "Hero", "role": "player", "params": {"hp": 5}},
                      {"name": "Coin", "role": "collectible"}, {"name": "Gone", "role": "goal"},
                      {"name": "Rock"}]}
    assert opening.apply_spec(objects, spec, set_role) == 2
    assert tagged == {"Hero": ("player", {"hp": 5}), "Coin": ("collectible", {})}
    assert opening.apply_spec(objects, {}, set_role) == 0


# --- publishing a remix ---------------------------------------------------------

def ctx(**extra):
    return {"title": "Ash Glaive (remix)", "slug": "ash-glaive-remix", "store_page": {}, **extra}


def test_store_fields_carry_lineage_and_the_switch():
    fields = pipeline.store_fields(ctx(remixed_from=ORIGIN), ["web"])
    assert fields["remixed_from_id"] == ORIGIN["id"] and fields["allow_remix"] is True
    plain = pipeline.store_fields(ctx(allow_remix=False), ["web"])
    assert "remixed_from_id" not in plain and plain["allow_remix"] is False
    # A game can't name a post as its parent.
    assert "remixed_from_id" not in pipeline.store_fields(ctx(remixed_from=dict(ORIGIN, kind="post")), ["web"])
    # Lineage is set once, at creation; an update never resends it (or the slug).
    assert set(pipeline._for_update(fields)) == set(fields) - {"slug", "remixed_from_id"}


class FakeStore:
    def __init__(self, fail_at=""):
        self.calls, self.fail_at = [], fail_at

    def _call(self, name, *args):
        self.calls.append((name, *args))
        if name == self.fail_at:
            raise StoreError("The store said no.", "too_large", 413)

    def update_game(self, game_id, fields):
        self._call("update_game", game_id, fields)
        return {"id": game_id}

    def create_media(self, game_id, kind, filename, size, digest):
        self._call("create_media", game_id, kind, filename, size, digest)
        return {"upload_id": "u1", "put_url": "http://put", "headers": {"X": "1"}}

    def upload(self, url, headers, path, on_progress, cancel):
        self._call("upload", url, headers, os.path.basename(path))

    def complete_media(self, game_id, upload_id):
        self._call("complete_media", game_id, upload_id)


def test_republishing_a_remix_never_resends_lineage():
    client = FakeStore()
    fields = pipeline.store_fields(ctx(remixed_from=ORIGIN, store={"game_id": "g1"}), ["web"])
    pipeline._create_or_update(client, ctx(store={"game_id": "g1"}), fields)
    name, game_id, sent = client.calls[0]
    assert (name, game_id) == ("update_game", "g1") and "remixed_from_id" not in sent and "slug" not in sent


@pytest.fixture
def captured(tmp_path):
    folder = tmp_path / "game" / ".remix_source" / "abc"
    folder.mkdir(parents=True)
    copy = folder / "ash-glaive-remix.mixar"
    copy.write_bytes(b"cleaned project")
    return {"folder": str(folder), "copy": str(copy), "source": "", "binary": "mixar",
            "result": str(folder / "result.json")}


def test_the_cleaned_project_is_uploaded_as_the_source(captured, monkeypatch):
    monkeypatch.setattr(source_job, "stage", lambda source, cancel=None: source["copy"])
    client, handle = FakeStore(), NS(cancel_event=threading.Event())
    assert pipeline._upload_source(client, handle, "g1", {"remix_source": captured}) == ""
    kinds = [call[0] for call in client.calls]
    assert kinds == ["create_media", "upload", "complete_media"]
    _n, game_id, kind, filename, size, digest = client.calls[0]
    assert (game_id, kind, filename, size) == ("g1", "source", "ash-glaive-remix.mixar", 15)
    assert digest == hashlib.sha256(b"cleaned project").hexdigest()
    assert not os.path.exists(captured["folder"])  # the temporary copy is always removed


@pytest.mark.parametrize("problem", ["unprepared", "create_media", "upload"])
def test_a_failed_source_is_a_warning_never_a_failed_publish(captured, monkeypatch, problem):
    monkeypatch.setattr(source_job, "stage",
                        lambda source, cancel=None: "" if problem == "unprepared" else source["copy"])
    client = FakeStore(fail_at=problem)
    warning = pipeline._upload_source(client, NS(cancel_event=threading.Event()), "g1",
                                      {"remix_source": captured})
    assert warning.startswith("The project was not included for remixing")
    assert not os.path.exists(captured["folder"])
    assert pipeline._upload_source(client, None, "g1", {}) == ""  # remixing switched off


def test_the_uncleaned_copy_is_removed_when_a_publish_fails_early(captured, monkeypatch):
    """Before the upload step the captured copy is the creator's raw project."""
    def boom(ctx):
        raise JobError("Mixar Godot was not found.", "godot_missing")

    monkeypatch.setattr(pipeline, "_godot_verdict", boom)
    work = pipeline.publish_work({"remix_source": captured, "game_dir": "/nowhere"}, ["web"])
    with pytest.raises(JobError):
        work(NS(cancel_event=threading.Event(), progress=lambda *a, **k: None))
    assert not os.path.exists(captured["folder"])


def test_a_failed_bake_also_removes_the_copy(captured, tmp_path):
    from mixar.modules.game_studio.core import bake_job
    work = pipeline.publish_work({"remix_source": captured, "game_dir": str(tmp_path)}, ["web"])
    bake = {"folder": str(tmp_path / "bake"), "copy": "x", "config": "c", "binary": "/no/such/mixar",
            "result": str(tmp_path / "r.json"), "source": "", "dirty": []}
    wrapped = bake_job.with_bake(bake, work)
    with pytest.raises(JobError):
        wrapped(NS(job_id="j", cancel_event=threading.Event(), cancelled=False, progress=lambda *a, **k: None))
    assert not os.path.exists(captured["folder"])


def test_store_identity_is_only_written_to_the_file_that_was_published(monkeypatch):
    from mixar.modules.game_studio.core import jobs
    scene = {}
    fake = NS(data=NS(filepath="/projects/remix.mixar", scenes=NS(get=lambda name: scene)))
    monkeypatch.setitem(__import__("sys").modules, "bpy", fake)
    queued = []
    monkeypatch.setattr(jobs, "call_on_main", queued.append)
    pipeline._remember("Scene", {"game_id": "A"}, "/projects/original.mixar")
    queued.pop()()
    assert scene == {}  # another file is open now: nothing is stamped on it
    pipeline._remember("Scene", {"game_id": "A"}, "/projects/remix.mixar")
    queued.pop()()
    assert json.loads(scene["mixar_game_store"]) == {"game_id": "A"}


def test_source_cleaning_runs_without_autoexec_and_reports_failure(captured):
    seen = {}

    def runner(binary, args, result_path, action, cancel=None, timeout=0, schema=""):
        seen.update(binary=binary, args=args, action=action, schema=schema)
        return {"ok": seen.get("ok", True)}

    assert source_job.stage(captured, runner=runner) == captured["copy"]
    assert seen["args"][:3] == ["-Y", "-b", captured["copy"]] and seen["action"] == "remix_source"
    assert seen["args"][-2].endswith("source_child.py") and seen["schema"] == "mixar_remix_source_result_v1"
    seen["ok"] = False
    assert source_job.stage(captured, runner=runner) == ""


# --- wiring -----------------------------------------------------------------------

def test_starting_a_remix_is_denied_to_agent_scripts():
    from mixar.modules.space_mixie_chat.core.sandbox_denylist import DENIED_OPS
    assert "mixar.remix_start" in DENIED_OPS


def test_macos_bundle_registers_the_mixar_link():
    with open(os.path.join(REPO, "src/release/darwin/Mixar.app/Contents/Info.plist"), "rb") as handle:
        text = handle.read()
    start = text.index(b"<key>CFBundleURLTypes</key>")
    block = text[start:text.index(b"<key>CFBundleExecutable</key>", start)]
    assert b"<string>mixar</string>" in block
    # .mixar documents still open the app.
    assert b"<string>com.mixar.mixar.file</string>" in text
    schemes = [s for t in plistlib.loads(text.replace(b"${MACOSX_BUNDLE_LONG_VERSION_STRING}", b"x")
                                         )["CFBundleURLTypes"] for s in t["CFBundleURLSchemes"]]
    assert schemes == ["mixar"]
