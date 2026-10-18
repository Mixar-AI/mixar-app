# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Store client request shapes (contract §4) against a stub HTTP server."""

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from mixar.modules.game_studio.core import store_client
from mixar.modules.game_studio.core.store_client import StoreClient, StoreError


class _Stub(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _reply(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        server = self.server
        server.calls.append({"method": self.command, "path": self.path,
                             "headers": dict(self.headers), "raw": raw})
        status, body = server.routes.get((self.command, self.path), (404, {"detail": {
            "code": "not_found", "message": "No such route"}}))
        if callable(body):
            status, body = body(raw)
        self._reply(status, body)

    do_GET = do_POST = do_PATCH = do_PUT = _handle


@pytest.fixture
def stub():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
    server.calls, server.routes = [], {}
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server.base = f"http://127.0.0.1:{server.server_address[1]}"
    yield server
    server.shutdown()


def _envelope(data):
    return {"status": "success", "message": "ok", "data": data}


def _client(stub, token="tok-123", refresh=lambda: False):
    return StoreClient(stub.base, token_provider=lambda: token, refresh=refresh)


def test_create_game_sends_bearer_and_contract_fields(stub):
    stub.routes[("POST", "/api/v1/games")] = (201, _envelope({"game": {"id": "g1", "slug": "crystal-run"}}))
    game = _client(stub).create_game({"title": "Crystal Run", "slug": "crystal-run", "tagline": "",
                                      "description": "", "genres": [], "tags": [], "price_cents": 0,
                                      "platforms": ["web"], "content_rating": "everyone"})
    assert game == {"id": "g1", "slug": "crystal-run"}
    call = stub.calls[0]
    assert call["headers"]["Authorization"] == "Bearer tok-123"
    body = json.loads(call["raw"])
    assert body["source"] == "mixar" and body["price_cents"] == 0 and body["platforms"] == ["web"]


def test_build_flow_hashes_and_uploads_without_bearer(stub, tmp_path):
    artifact = tmp_path / "game-web.zip"
    artifact.write_bytes(b"PK" + b"x" * 300000)
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    stub.routes[("POST", "/api/v1/games/g1/builds")] = (200, _envelope({
        "build_id": "b1", "put_url": stub.base + "/incoming/b1", "headers": {"Content-Type": "application/zip"}}))
    stub.routes[("PUT", "/incoming/b1")] = (200, {})
    stub.routes[("POST", "/api/v1/games/g1/builds/b1/complete")] = (200, _envelope({
        "build": {"review_status": "pending"}}))
    client = _client(stub)
    sha, size = store_client.sha256_file(str(artifact))
    assert (sha, size) == (digest, artifact.stat().st_size)
    slot = client.create_build("g1", "web", "2026.10.17", "game-web.zip", size, sha)
    progress = []
    client.upload(slot["put_url"], slot["headers"], str(artifact), progress.append)
    done = client.complete_build("g1", "b1")
    create, put, _complete = stub.calls
    assert json.loads(create["raw"]) == {"platform": "web", "version": "2026.10.17",
                                         "filename": "game-web.zip", "size_bytes": size, "sha256": digest}
    assert "Authorization" not in put["headers"]  # never leak the bearer to storage
    assert put["headers"]["Content-Length"] == str(size)
    assert "chunked" not in put["headers"].get("Transfer-Encoding", "")
    assert hashlib.sha256(put["raw"]).hexdigest() == digest
    assert progress and progress[-1] == pytest.approx(1.0)
    assert done["build"]["review_status"] == "pending"


def test_http_error_surfaces_store_detail(stub):
    stub.routes[("POST", "/api/v1/games/g1/publish")] = (409, {"detail": {
        "code": "no_builds", "message": "Upload a build first"}})
    with pytest.raises(StoreError) as caught:
        _client(stub).publish("g1")
    assert (caught.value.code, caught.value.message, caught.value.status) == \
        ("no_builds", "Upload a build first", 409)


def test_401_refreshes_once_then_retries(stub):
    tokens = iter(["old", "new"])
    state = {"token": next(tokens)}

    def refresh():
        state["token"] = next(tokens)
        return True

    stub.routes[("GET", "/api/v1/games/g1")] = (200, lambda raw: (
        (200, _envelope({"game": {"id": "g1"}})) if stub.calls[-1]["headers"]["Authorization"] == "Bearer new"
        else (401, {"detail": {"code": "unauthorized", "message": "expired"}})))
    client = StoreClient(stub.base, token_provider=lambda: state["token"], refresh=refresh)
    assert client.get_game("g1") == {"id": "g1"}
    assert len(stub.calls) == 2


def test_missing_token_is_login_required(stub):
    with pytest.raises(StoreError) as caught:
        _client(stub, token="").get_game("g1")
    assert caught.value.code == "login_required" and not stub.calls


def test_transport_failure_is_classified():
    client = StoreClient("http://127.0.0.1:1", token_provider=lambda: "t")
    with pytest.raises(StoreError) as caught:
        client.get_game("g1")
    assert caught.value.code.startswith("NET-")
    assert "Unable to connect" not in caught.value.message


def test_store_client_never_sets_verify_or_proxies():
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(store_client))
    keywords = {kw.arg for node in ast.walk(tree) if isinstance(node, ast.Call) for kw in node.keywords}
    assert not keywords & {"verify", "proxies", "cert"}


def test_validation_422_and_slug_conflict_detail(stub):
    stub.routes[("POST", "/api/v1/games")] = (409, {"detail": {
        "code": "slug_taken", "message": "That store address is taken", "game_id": "g7"}})
    stub.routes[("PATCH", "/api/v1/games/g1")] = (422, {"detail": [
        {"loc": ["body", "price_cents"], "msg": "paid games start at $1.00", "type": "value_error"}]})
    client = _client(stub)
    with pytest.raises(StoreError) as caught:
        client.create_game({"title": "x", "slug": "crystal-run"})
    assert caught.value.code == "slug_taken" and caught.value.detail == {"game_id": "g7"}
    with pytest.raises(StoreError) as caught:
        client.update_game("g1", {"price_cents": 50})
    assert caught.value.code == "invalid_request" and "paid games" in caught.value.message


def test_slug_conflict_on_own_draft_updates_it(stub):
    from mixar.modules.game_studio.core import pipeline
    stub.routes[("POST", "/api/v1/games")] = (409, {"detail": {
        "code": "slug_taken", "message": "taken", "game_id": "g7"}})
    stub.routes[("PATCH", "/api/v1/games/g7")] = (200, _envelope({"id": "g7", "slug": "crystal-run"}))
    game = pipeline._create_or_update(_client(stub), {"store": {}}, {"title": "Crystal Run",
                                                                     "slug": "crystal-run"})
    assert game["id"] == "g7"
    assert "slug" not in json.loads(stub.calls[-1]["raw"])


def test_slug_taken_game_id_in_data_and_media_flow(stub, tmp_path):
    stub.routes[("POST", "/api/v1/games")] = (409, {"detail": {"code": "slug_taken", "message": "taken"},
                                                    "data": {"game_id": "g8"}})
    with pytest.raises(StoreError) as caught:
        _client(stub).create_game({"title": "x", "slug": "abc"})
    assert caught.value.detail["game_id"] == "g8"
    image = tmp_path / "capsule.png"
    image.write_bytes(b"\x89PNG" + b"0" * 100)
    stub.routes[("POST", "/api/v1/games/g8/media")] = (201, _envelope({
        "upload_id": "m1", "put_url": stub.base + "/up/m1", "method": "PUT", "headers": {"Content-Type": "image/png"}}))
    stub.routes[("PUT", "/up/m1")] = (200, {})
    stub.routes[("POST", "/api/v1/games/g8/media/m1/complete")] = (200, _envelope({}))
    from mixar.modules.game_studio.core import pipeline
    assert pipeline._upload_capsule(_client(stub), "g8", str(image), None) == ""
    declare, put, _done = stub.calls[1:]
    assert json.loads(declare["raw"])["kind"] == "capsule"
    assert "Authorization" not in put["headers"] and put["headers"]["Content-Type"] == "image/png"
