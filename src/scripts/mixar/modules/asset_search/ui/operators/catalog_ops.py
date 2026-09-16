# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Asset and biome search UI backed by the same catalog RPC the agent uses."""

import threading

import bpy
from bpy.types import Operator
from bpy.props import BoolProperty, StringProperty

from mixar.modules.asset_search.core.catalog import service
from mixar.modules.asset_search.core.agent_tools import run_tool


def _fill(state, result):
    state.search_results.clear()
    for hit in result.get('results', []):
        row = state.search_results.add()
        row.name = hit['name']
        row.library = hit['library']
        row.blend_file = hit['blend_file']
        row.asset_type = hit['type']
        row.asset_id = hit['asset_id']
        row.revision = hit['revision']
        row.available = hit['available']
        row.scatterable = hit['scatterable']
        row.score = float(hit.get('semantic_score', 0))
    state.search_message = ('Indexing libraries…' if result.get('indexing') else
                            result.get('message') or f"{len(state.search_results)} assets found")


class MIXIE_OT_catalog_refresh(Operator):
    bl_idname = 'mixie.catalog_refresh'
    bl_label = 'Refresh Libraries'
    bl_description = 'Index asset names, tags and descriptions in the background; preserve unavailable libraries'

    def execute(self, context):
        result = run_tool(context.scene, 'refresh_libraries')
        if result.get('error'):
            self.report({'ERROR'}, result['error'])
            return {'CANCELLED'}
        if not context.scene.mixie_asset_training.is_searching:
            bpy.ops.mixie.catalog_search(use_semantic=False)
        return {'FINISHED'}


class MIXIE_OT_catalog_search(Operator):
    bl_idname = 'mixie.catalog_search'
    bl_label = 'Search Assets'
    bl_description = 'Search library assets and biome assets by name, tags, description and trained semantic matches'
    _timer = None
    _thread = None
    _result = None
    use_semantic: BoolProperty(default=True, options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        state = getattr(context.scene, 'mixie_asset_training', None)
        return state is not None and not state.is_searching

    def execute(self, context):
        state = context.scene.mixie_asset_training
        self._scene = context.scene
        self._thread = None
        self._result = None
        self._params = {'query': state.search_prompt, 'libraries': [state.catalog_library] if state.catalog_library else None,
                        'scatterable': state.catalog_scatter_only, 'limit': 30}
        image_bytes = None
        if self.use_semantic and state.search_image:
            from .asset_search_ops import _extract_search_image_bytes
            if not state.has_model:
                self.report({'ERROR'}, 'Train a library before searching by reference image')
                return {'CANCELLED'}
            image_bytes = _extract_search_image_bytes(state.search_image)
            if not image_bytes:
                self.report({'ERROR'}, 'Could not read the reference image')
                return {'CANCELLED'}
        result = run_tool(context.scene, 'search', self._params)
        if result.get('error'):
            self.report({'ERROR'}, result['error'])
            return {'CANCELLED'}
        _fill(state, result)
        self._source_id = result.get('source_id', '')
        self._library_names = [lib['name'] for lib in result.get('libraries', [])
                               if lib['name'] == state.catalog_library or lib['id'] == state.catalog_library] if state.catalog_library else None
        if self.use_semantic and state.has_model and (state.search_prompt.strip() or image_bytes):
            from .asset_search_ops import _search_api
            self._thread = threading.Thread(target=_search_api,
                args=(state.search_prompt, image_bytes, self), daemon=True)
            self._thread.start()
        if not result.get('indexing') and self._thread is None:
            return {'FINISHED'}
        state.is_searching = True
        self._timer = context.window_manager.event_timer_add(.2, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'ESC':
            self.cancel(context)
            return {'CANCELLED'}
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}
        if (self._thread and self._thread.is_alive()) or service.status()['indexing']:
            return {'RUNNING_MODAL'}
        try:
            _fill(self._scene.mixie_asset_training,
                  service.search(**self._params, semantic_candidates=(self._result or {}).get('results', [])))
            if self._result and not self._result.get('success'):
                self._scene.mixie_asset_training.search_message = 'Semantic search unavailable; showing local matches'
        except ReferenceError:
            pass  # The original scene was closed while the request ran.
        finally:
            self.cancel(context)
        return {'FINISHED'}

    def cancel(self, context):
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        try:
            self._scene.mixie_asset_training.is_searching = False
        except ReferenceError:
            pass
        for area in context.screen.areas:
            area.tag_redraw()


class MIXIE_OT_catalog_place(Operator):
    bl_idname = 'mixie.catalog_place'
    bl_label = 'Add Asset'
    bl_description = 'Place this exact asset at the cursor, or scatter it on the selected mesh using Scatter settings'
    bl_options = {'REGISTER', 'UNDO'}
    asset_id: StringProperty()
    revision: StringProperty()
    mode: StringProperty(default='append')

    def execute(self, context):
        state = context.scene.mixie_asset_training
        if self.mode == 'scatter':
            surface = context.view_layer.objects.active
            if surface is None or surface.type != 'MESH':
                self.report({'ERROR'}, 'Select a mesh surface to scatter on')
                return {'CANCELLED'}
            params = {'surface_name': surface.name, 'layers': [{'asset_id': self.asset_id,
                'revision': self.revision, 'count': state.scatter_count,
                'scale': [state.scatter_scale_min, state.scatter_scale_max],
                'min_distance': state.scatter_spacing}], 'seed': state.scatter_seed}
        else:
            params = {'asset_id': self.asset_id, 'revision': self.revision,
                      'location': list(context.scene.cursor.location)}
        result = run_tool(context.scene, self.mode, params)
        if not result.get('success'):
            self.report({'ERROR'}, result.get('error', 'Could not place asset'))
            return {'CANCELLED'}
        self.report({'INFO'}, f"Placed {result['placed']} instances" if self.mode == 'scatter' else 'Asset added at the 3D cursor')
        return {'FINISHED'}


classes = (MIXIE_OT_catalog_refresh, MIXIE_OT_catalog_search, MIXIE_OT_catalog_place)
