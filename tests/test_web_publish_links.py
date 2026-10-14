# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Publish links are untrusted .blend data: only https links on the API
host or its parent domain are opened, copied, stored or given to the agent;
and the agent path works without UI auto-discovery (headless workers)."""

import ast
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from mixar.modules.web_publish.core import links
from mixar.modules.web_publish.core.publish_state import PublishResult

API = "https://api.mixar.app"
OPS = (Path(__file__).resolve().parents[1]
       / "src/scripts/mixar/modules/web_publish/ui/operators/publish_ops.py")


def test_trusted_hosts_are_the_api_host_and_its_parent_domain():
    assert links.trusted_hosts(API) == ("api.mixar.app", "mixar.app")
    assert links.trusted_hosts("http://localhost:8000") == ("localhost",)
    assert links.trusted_hosts("https://127.0.0.1") == ("127.0.0.1",)
    assert links.trusted_hosts("") == ()


@pytest.mark.parametrize("url", [
    "https://api.mixar.app/api/v1/scene-publish/s/loft",
    "https://scenes.mixar.app/s/loft",
    "https://mixar.app/s/loft",
])
def test_https_links_on_trusted_hosts_pass(url):
    assert links.is_safe_share_link(url, links.trusted_hosts(API))


@pytest.mark.parametrize("url", [
    "http://api.mixar.app/s/loft",
    "file:///etc/passwd",
    "javascript:alert(1)",
    "https://evil.example.com/s/loft",
    "https://mixar.app.evil.com/s/loft",
    "https://evilmixar.app/s/loft",
    "https://user:pw@api.mixar.app/s/loft",
    "",
])
def test_unsafe_links_fail(url):
    assert not links.is_safe_share_link(url, links.trusted_hosts(API))


def test_open_and_copy_validate_in_poll_and_execute():
    tree = ast.parse(OPS.read_text(encoding="utf-8"))
    for name in ("MIXAR_OT_web_publish_copy_link", "MIXAR_OT_web_publish_open"):
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name)
        for method in ("poll", "execute"):
            fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == method)
            assert "_safe_link" in ast.unparse(fn), (name, method)
    source = OPS.read_text(encoding="utf-8")
    assert "is_safe_share_link(link)" in source and '"Invalid link"' in source


def test_pipeline_refuses_to_store_an_untrusted_link(monkeypatch):
    from mixar.modules.web_publish.core import pipeline

    trusted = links.trusted_hosts(API)
    monkeypatch.setattr(links, "trusted_hosts", lambda api_url=None: trusted)
    monkeypatch.setattr(pipeline, "_telemetry", lambda *a: None)
    props = SimpleNamespace()
    monkeypatch.setattr(pipeline, "bpy", SimpleNamespace(data=SimpleNamespace(
        scenes={"Loft": SimpleNamespace(mixar_web_publish=props)})))
    progress = SimpleNamespace(status="DONE")
    pipeline._apply_outcome("Loft", "agent", progress, PublishResult(
        scene_id="s", slug="loft", revision=1, share_url="javascript:alert(1)",
        viewer_url="https://scenes.mixar.app/s/loft"))
    assert props.share_url == "" and props.viewer_url == "https://scenes.mixar.app/s/loft"


def test_start_publish_registers_properties_without_ui_discovery(monkeypatch):
    """--background workers never run the ui/ batches: start_publish must
    register the properties itself and reach the real refusal."""
    from mixar.modules.web_publish.core import agent_api, pipeline, registration

    monkeypatch.delitem(sys.modules, registration.PROPERTIES_MODULE, raising=False)
    scene_type = SimpleNamespace()  # no mixar_web_publish yet
    scene = SimpleNamespace(name="Loft")
    registered = []

    def register():
        registered.append(True)
        scene_type.mixar_web_publish = True
        scene.mixar_web_publish = SimpleNamespace(
            title="", description="", visibility="public", include_animation=True,
            published_scene_id="", slug="")

    fake_bpy = SimpleNamespace(types=SimpleNamespace(Scene=scene_type),
                               context=SimpleNamespace(scene=scene))
    monkeypatch.setitem(sys.modules, "bpy", fake_bpy)
    monkeypatch.setattr(registration.importlib, "import_module",
                        lambda name: SimpleNamespace(register=register))
    monkeypatch.setattr(pipeline, "_signed_in", lambda: False)
    out = agent_api.start_publish({"title": "x"})
    assert registered == [True]
    assert out["status"] == "failed" and "Sign in" in out["error"]
    assert "not available" not in out["error"]
