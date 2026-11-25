# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Image Upscale (Topaz on fal): one source still, one contract.

Pins the catalog-read limits and the early output-cap check, the ONE enqueue
path the node and the agent operator share (a staged source under the
``image_upscale`` upload purpose, landing as ``image_s3_key``), the staged
image job, and every registry the node type must appear in (queue bucket,
action/output/capability maps, template, menus, C++ output-kind table).
"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType, SimpleNamespace
import io
import re
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / "src/scripts/mixar/modules"
MOODBOARD = MODULES / "moodboard"
SPACE_MIXIE = ROOT / "src/source/blender/editors/space_mixie"
CATALOG_MODULE = "mixar.bootstrap.generation_catalog_cache"

sys.path.insert(0, str(ROOT / "src/scripts"))
if "keyring" not in sys.modules:
    sys.modules["keyring"] = ModuleType("keyring")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _catalog():
    spec = spec_from_file_location(
        "image_upscale_catalog_under_test", MOODBOARD / "core/image_upscale_catalog.py"
    )
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _stub(service):
    module = ModuleType(CATALOG_MODULE)
    module.get_service = lambda _key: service
    return module


def _service(**overrides):
    image = {
        "name": "image", "kind": "image", "required": True, "multiple": False,
        "max_count": 1, "max_size_mb": 30, "max_pixels": 96_000_000,
        "max_output_pixels": 96_000_000, "upload_purpose": "image_upscale",
    }
    image.update(overrides)
    return {"input_spec": {"inputs": [image], "max_materials": 1}}


LIMITS = {
    "max_bytes": 30 * 1024 * 1024, "max_pixels": 96_000_000,
    "max_output_pixels": 96_000_000, "upload_purpose": "image_upscale",
}


# --------------------------------------------------------------------------- #
# Catalog contract (standalone, no bpy)
# --------------------------------------------------------------------------- #


def test_limits_come_from_the_catalog_service(monkeypatch):
    monkeypatch.setitem(sys.modules, CATALOG_MODULE, _stub(_service()))
    assert _catalog().get_image_upscale_limits() == LIMITS


@pytest.mark.parametrize("broken", [
    {},
    {"input_spec": {"inputs": []}},
    _service(max_output_pixels=0),
    _service(max_size_mb="lots"),
    _service(multiple=True),
])
def test_malformed_catalog_rows_fail_closed(monkeypatch, broken):
    monkeypatch.setitem(sys.modules, CATALOG_MODULE, _stub(broken))
    assert _catalog().get_image_upscale_limits() is None


def test_output_cap_is_checked_before_upload_with_the_largest_factor_that_fits():
    catalog = _catalog()
    assert catalog.image_upscale_source_error(2048, 2048, 4, LIMITS) is None
    message = catalog.image_upscale_source_error(4000, 4000, 4, LIMITS)
    assert "2.4x or less" in message
    assert catalog.max_factor_for(4000, 4000, 96_000_000) == 2.4
    # The default factor applies when the node has no value yet.
    assert catalog.image_upscale_source_error(9000, 9000, None, LIMITS)
    assert "megapixels" in catalog.image_upscale_source_error(12000, 9000, 1, LIMITS)
    assert catalog.image_upscale_source_error(0, 10, 2, LIMITS)
    # A sub-megapixel cap is named, never rounded down to "0 megapixel".
    small = dict(LIMITS, max_output_pixels=500_000)
    assert "0.5 megapixel" in catalog.image_upscale_source_error(256, 192, 4, small)


# --------------------------------------------------------------------------- #
# The shared enqueue path
# --------------------------------------------------------------------------- #


def test_enqueue_stages_the_source_under_the_upscale_purpose(monkeypatch):
    from mixar.modules.common import job_queue as job_queue_pkg
    from mixar.modules.moodboard.core import image_upscale_enqueue as enqueue

    captured = {}
    monkeypatch.setattr(
        job_queue_pkg, "enqueue_generation",
        lambda **kwargs: captured.update(kwargs) or SimpleNamespace(id="job-1"),
    )
    source = {"filename": "photo.png", "mime_type": "image/png", "bytes": b"x"}

    job = enqueue.enqueue_image_upscale(
        service_key="image_upscale", model="topaz-cgi",
        params={"upscale_factor": 2.0}, source_input=source, limits=LIMITS,
        source_name="photo.png", graph_node_id="abcdef0123", on_imported="hook",
    )

    assert job.id == "job-1"
    assert captured["kind"] == "image"
    assert captured["feature_key"] == "image_upscale"
    assert captured["job_type"] == "image_upscale"
    assert captured["model"] == "topaz-cgi"
    assert captured["origin_capability_key"] == "image_upscale"
    assert captured["payload"] == {"params": {"upscale_factor": 2.0}}
    assert captured["source_image"] is source
    assert captured["upload_purpose"] == "image_upscale"
    assert captured["source_key_field"] == "image_s3_key"
    assert captured["base_name"] == "photo_upscaled"
    assert captured["on_imported"] == "hook"
    assert captured["label"].startswith("ImageUpscale:abcdef01:")


def test_sniffing_matches_the_backend_uploader():
    from mixar.modules.moodboard.core.image_upscale_enqueue import sniff_image

    assert sniff_image(b"\x89PNG\r\n\x1a\n....") == ("png", "image/png")
    assert sniff_image(b"\xff\xd8\xff\xe0....") == ("jpg", "image/jpeg")
    assert sniff_image(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == ("webp", "image/webp")
    assert sniff_image(b"\x76\x2f\x31\x01EXR") is None  # re-encoded as PNG


def test_staged_job_uploads_then_submits_with_the_key(monkeypatch):
    from mixar.modules.common.api.services import job_queue_service as jqs
    from mixar.modules.common.job_queue.core.staged_image_job import StagedImageJob

    calls = []

    class Service:
        def stage_media(self, **kwargs):
            calls.append(("stage", kwargs))
            body = kwargs["body_factory"]()
            assert isinstance(body, io.BytesIO) and body.read() == b"PNGDATA"
            kwargs["on_success"](SimpleNamespace(data={"data": {"s3_key": "k/1x1/a.png"}}))

        def enqueue(self, **kwargs):
            calls.append(("enqueue", kwargs))

    monkeypatch.setattr(jqs, "get_job_queue_service", lambda: Service())
    job = StagedImageJob(
        feature_key="image_upscale", label="ImageUpscale: a", job_type="image_upscale",
        model="topaz-cgi", payload={"params": {}},
        source_input={"filename": "a.png", "mime_type": "image/png", "bytes": b"PNGDATA"},
        upload_purpose="image_upscale",
    )
    job.submit(lambda *_: None, lambda exc: calls.append(("error", exc)))

    assert [name for name, _ in calls] == ["stage", "enqueue"]
    assert calls[0][1]["media_kind"] == "image"
    assert calls[0][1]["purpose"] == "image_upscale"
    assert calls[1][1]["payload"] == {"params": {}, "image_s3_key": "k/1x1/a.png"}
    assert job.source_input == {}  # bytes released once staged


def test_staging_without_a_key_fails_the_job(monkeypatch):
    from mixar.modules.common.api.services import job_queue_service as jqs
    from mixar.modules.common.job_queue.core.staged_image_job import StagedImageJob

    errors = []

    class Service:
        def stage_media(self, **kwargs):
            kwargs["on_success"](SimpleNamespace(data={"data": {}}))

    monkeypatch.setattr(jqs, "get_job_queue_service", lambda: Service())
    StagedImageJob(
        feature_key="image_upscale", job_type="image_upscale",
        source_input={"filename": "a.png", "bytes": b"x"},
    ).submit(lambda *_: None, errors.append)
    assert errors and "s3_key" in str(errors[0])


def test_enqueue_generation_builds_a_staged_job_only_with_a_source():
    source = _read(MODULES / "common/job_queue/core/enqueue.py")
    assert "StagedImageJob if source_image else SyncImageJob" in source
    assert '"upload_purpose": upload_purpose' in source
    assert '"source_key_field": source_key_field' in source


# --------------------------------------------------------------------------- #
# Surfaces and registries
# --------------------------------------------------------------------------- #


def test_node_and_agent_share_one_enqueue():
    runner = _read(MOODBOARD / "core/image_upscale_enqueue.py")
    execution = _read(MOODBOARD / "core/node_execution.py")
    agent = _read(MOODBOARD / "ui/operators/agent_image_upscale_ops.py")
    assert "run_image_upscale_node" in execution
    assert "'IMAGE_UPSCALE'" in execution
    for name in ("prepare_image_upscale_source", "enqueue_image_upscale"):
        assert name in agent and name in runner
    assert "import enqueue_generation" not in agent
    assert 'bl_idname = "mixie.agent_image_upscale"' in agent
    assert "set_agent_gen_reason" in agent
    operators = _read(MOODBOARD / "ui/operators/__init__.py")
    assert operators.count("agent_image_upscale_ops,") == 2  # imported AND registered


def test_feature_is_registered_in_the_queue():
    constants = _read(MODULES / "common/job_queue/constants.py")
    assert 'FEATURE_IMAGE_UPSCALE = "image_upscale"' in constants
    assert '"FEATURE_IMAGE_UPSCALE",' in constants
    queue = _read(MODULES / "common/job_queue/ui/properties/queue_properties.py")
    features = queue[queue.index("_FEATURES = ("):]
    assert "FEATURE_IMAGE_UPSCALE" in features[:features.index(")")]


def test_node_type_is_appended_and_mirrored_in_cpp():
    from mixar.modules.moodboard.core.node_action_types import ACTION_TYPES
    from mixar.modules.moodboard.core import node_schema

    ids = [entry[0] for entry in ACTION_TYPES]
    assert ids[-1] == 'IMAGE_UPSCALE'
    assert node_schema.output_type_for_action('IMAGE_UPSCALE') == 'IMAGE'
    assert node_schema._capability_for_action('IMAGE_UPSCALE') == 'image_upscale'
    assert 'IMAGE_UPSCALE' in node_schema._PROMPTLESS_ACTION_TYPES
    services = [{"key": "image_upscale"}, {"key": "image_gen"}]
    assert node_schema.services_for_action('IMAGE_UPSCALE', services) == [services[0]]

    cpp = _read(SPACE_MIXIE / "mixie_draw_moodboard_graph_sockets.cc")
    table = re.search(r"ACTION_OUTPUT_KINDS\[\] = \{([^}]*)\}", cpp).group(1)
    kinds = re.findall(r"'(\w)'", table)
    assert len(kinds) == len(ids)
    assert kinds[ids.index('IMAGE_UPSCALE')] == 'I'

    properties = _read(MOODBOARD / "ui/moodboard_graph_properties.py")
    assert "if action_type == 'IMAGE_UPSCALE':\n        return \"image_upscale\"" in properties


def test_template_and_menus_offer_it_only_for_stills():
    constants = _read(MOODBOARD / "constants.py")
    assert "('IMAGE_UPSCALE', n_(\"Upscale Image\"), 'ZOOM_IN', 'image_upscale')" in constants
    graph = _read(MOODBOARD / "core/node_graph.py")
    assert "'IMAGE_UPSCALE': {'IMAGE'}," in graph
    assert "Upscale Image needs one selected image" in graph
    templates = _read(MOODBOARD / "core/node_templates.py")
    assert "stills_only = {'IMAGE_GEN', 'MODEL_3D', 'WORLD_LABS', 'IMAGE_UPSCALE'}" in templates
    menus = _read(MOODBOARD / "ui/moodboard_menus.py")
    assert menus.count("'IMAGE_UPSCALE', n_(\"Upscale Image\")") == 2
    assert "selected_stills > 0 and template_available('IMAGE_UPSCALE')" in menus
    output = _read(MOODBOARD / "ui/moodboard_output_menu.py")
    assert "source_type == 'IMAGE' and template_available('IMAGE_UPSCALE')" in output
