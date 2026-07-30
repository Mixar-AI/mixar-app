# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Steppable asset-preview render session.

The training flow used to render EVERY library asset inside one blocking
operator call — the UI froze and the progress bar sat still for the whole
(dominant) render phase. This module splits the work into an enumerable
plan plus a session that renders a few assets per call, so the training
modal can drive it from its timer and report true per-asset progress
(counter, current item, per-library breakdown, failures).

Used by ``ui/operators/asset_inspect_ops.py`` (which keeps its public
operator/API as a thin run-to-completion wrapper) and by the training
modal in ``ui/operators/asset_train_ops.py``.
"""

from pathlib import Path

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.asset_search.utils.preview_render import (
    PreviewRenderRig,
    frame_camera,
    image_from_preview,
    remove_collection,
    remove_objects,
    render_to_image,
)

logger = get_logger(__name__)


def convert_idprop_to_py(value):
    """Convert Blender IDProperty types to JSON-serializable Python types."""
    type_name = type(value).__name__
    if type_name == 'IDPropertyArray':
        return list(value)
    if isinstance(value, dict):
        return {k: convert_idprop_to_py(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [convert_idprop_to_py(item) for item in value]
    return value


def collect_asset_metadata(asset_id, library_name, blend_rel_path):
    """Metadata dict for an asset datablock (name/type/library/tags/...)."""
    asset_type = asset_id.type if hasattr(asset_id, 'type') else type(asset_id).__name__
    meta = asset_id.asset_data

    info = {
        'name': asset_id.name,
        'type': asset_type,
        'library': library_name,
        'blend_file': str(blend_rel_path),
        'author': '',
        'description': '',
        'copyright': '',
        'license': '',
        'catalog_id': '',
        'catalog_name': '',
        'tags': [],
        'custom_props': {},
        'image_name': '',
    }
    if meta is not None:
        info['author'] = meta.author or ''
        info['description'] = meta.description or ''
        info['copyright'] = meta.copyright or ''
        info['license'] = meta.license or ''
        info['catalog_id'] = meta.catalog_id or ''
        info['catalog_name'] = meta.catalog_simple_name or ''
        info['tags'] = [tag.name for tag in meta.tags] if meta.tags else []
        raw_props = dict(meta.items()) if hasattr(meta, 'items') else {}
        info['custom_props'] = {
            k: convert_idprop_to_py(v) for k, v in raw_props.items()
        }
    return info


def build_render_plan(context, identity_filter=None):
    """Enumerate every renderable asset as a work-item list, WITHOUT rendering.

    Walks the registered asset libraries, globs .blend files, and reads the
    asset-marked datablock names (metadata-only ``assets_only`` load — cheap).

    Args:
        context: Blender context (for preferences.filepaths.asset_libraries).
        identity_filter: Optional set of "name|library|blend_file" strings; when
            given, only matching assets enter the plan (incremental training).

    Returns:
        (items, discovery_failures) — items are dicts
        {kind: 'OBJECT'|'COLLECTION', blend_str, name, library, rel_path};
        discovery_failures are (label, reason) for unreadable .blend files.
    """
    items = []
    failures = []
    for lib in context.preferences.filepaths.asset_libraries:
        library_path = Path(lib.path)
        if not library_path.exists() or not library_path.is_dir():
            continue
        for blend_file in sorted(library_path.glob("**/*.blend")):
            rel_path = str(blend_file.relative_to(library_path))
            try:
                with bpy.data.libraries.load(
                    str(blend_file), assets_only=True
                ) as (data_from, _):
                    object_names = list(data_from.objects)
                    collection_names = list(data_from.collections)
            except Exception as e:
                failures.append((f"{lib.name}/{rel_path}", f"unreadable: {e}"))
                continue
            for kind, names in (
                ('OBJECT', object_names), ('COLLECTION', collection_names)
            ):
                for name in names:
                    if (identity_filter is not None
                            and f"{name}|{lib.name}|{rel_path}" not in identity_filter):
                        continue
                    items.append({
                        'kind': kind,
                        'blend_str': str(blend_file),
                        'name': name,
                        'library': lib.name,
                        'rel_path': rel_path,
                    })
    return items, failures


class RenderSession:
    """Renders a plan's items a few at a time, tracking progress + failures.

    Lifecycle: ``start()`` (enters the preview rig — scene mutated), then
    ``step(n)`` repeatedly until ``done``, then ``finish()`` (ALWAYS, also on
    cancel/error — restores the scene). ``collected`` holds the metadata dicts
    (with ``image_name`` set) for every successfully rendered asset;
    ``failures`` holds (label, reason) for every skipped one.
    """

    def __init__(self, context, items):
        self.context = context
        self.items = items
        self.index = 0
        self.collected = []
        self.failures = []
        self.current_label = ""
        self.preview_reused = 0  # thumbnails taken from the .blend, not rendered
        # Items we RENDERED because their .blend had no usable thumbnail —
        # candidates for writing the render back as the asset's preview
        # (kept separate from `collected`: absolute blend paths must never
        # ride the metadata uploaded to the server).
        self.rendered_items = []  # {blend_str, name, image_name}
        self._rig = None

    # -- lifecycle -------------------------------------------------------

    def start(self):
        self._rig = PreviewRenderRig(self.context.scene, size=512)
        self._rig.__enter__()

    def finish(self):
        if self._rig is not None:
            self._rig.__exit__(None, None, None)
            self._rig = None

    @property
    def total(self):
        return len(self.items)

    @property
    def done(self):
        return self.index >= len(self.items)

    def step(self, count=2, time_budget=0.12):
        """Process items until ``count`` OR ``time_budget`` seconds is hit.

        Always processes at least one item. The budget matters because items
        split into two speed classes: embedded-preview reuse (~ms) and full
        EEVEE renders (~0.5-1s) — a fixed per-tick count would either stall
        the UI on renders or crawl through previews one timer tick at a time.
        Returns the number attempted.
        """
        import time as _time

        started = _time.monotonic()
        attempted = 0
        while not self.done:
            item = self.items[self.index]
            self.index += 1
            attempted += 1
            self.current_label = f"{item['name']} ({item['library']})"
            try:
                self._render_item(item)
            except Exception as e:  # noqa: BLE001 — one bad asset must not stop the run
                logger.error("[RenderSession] Error rendering %s: %s",
                             item['name'], e)
                self.failures.append((self.current_label, str(e)[:120]))
            if _time.monotonic() - started >= time_budget:
                break
        return attempted

    # -- per-item render (adapted from the former monolithic operator) ----

    def _render_item(self, item):
        scene = self.context.scene
        with bpy.data.libraries.load(item['blend_str'], link=False) as (_, data_to):
            if item['kind'] == 'OBJECT':
                data_to.objects = [item['name']]
            else:
                data_to.collections = [item['name']]

        img_name = f"asset_preview_{item['name']}"

        if item['kind'] == 'OBJECT':
            obj = data_to.objects[0]
            if obj is None:
                self.failures.append((self.current_label, "not found in .blend"))
                return
            info = collect_asset_metadata(obj, item['library'], item['rel_path'])
            info['name'] = item['name']  # Blender may rename on append
            # Embedded thumbnail first — skips the whole main-thread render.
            img = image_from_preview(obj, img_name)
            if img is not None:
                self.preview_reused += 1
                info['reused_preview'] = True
                remove_objects([obj])
            else:
                scene.collection.objects.link(obj)
                bpy.context.view_layer.update()
                frame_camera(self._rig.camera, [obj])
                img = render_to_image(scene, img_name)
                scene.collection.objects.unlink(obj)
                remove_objects([obj])
        else:
            coll = data_to.collections[0]
            if coll is None:
                self.failures.append((self.current_label, "not found in .blend"))
                return
            info = collect_asset_metadata(coll, item['library'], item['rel_path'])
            info['name'] = item['name']
            img = image_from_preview(coll, img_name)
            if img is not None:
                self.preview_reused += 1
                info['reused_preview'] = True
                remove_collection(coll)
            else:
                scene.collection.children.link(coll)
                bpy.context.view_layer.update()
                objects = list(coll.all_objects)
                if not objects:
                    scene.collection.children.unlink(coll)
                    remove_collection(coll)
                    self.failures.append((self.current_label, "empty collection"))
                    return
                frame_camera(self._rig.camera, objects)
                img = render_to_image(scene, img_name)
                scene.collection.children.unlink(coll)
                remove_collection(coll)

        if img:
            info['image_name'] = img_name
            self.collected.append(info)
            if not info.get('reused_preview'):
                self.rendered_items.append({
                    'blend_str': item['blend_str'],
                    'name': item['name'],
                    'image_name': img_name,
                })
        else:
            self.failures.append((self.current_label, "render produced no image"))
