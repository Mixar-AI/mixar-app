# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Content-free intent and dispatch outcomes for the Blastoff surfaces.

An operator finishing means dispatch succeeded, never that an asynchronous
generation completed. The backend owns generation acceptance and completion.
"""

import time
import uuid

from .capture import capture
from .constants import EVENT_GENERATION_ATTEMPT, EVENT_GENERATION_DISPATCH, EVENT_UI_ACTION, EVENT_ISLAND_TAB
from .preferences import is_enabled

TABS = frozenset({'AGENT', 'THREE_D', 'IMAGE', 'VIDEO', 'SPLAT', 'GENERATIONS', 'QUEUE'})
OWNERS = {
    'MixieMoodboardTabImageGenProps': ('image_gen', 'tab_imagegen'),
    'MixieMoodboardTabLookdevProps': ('ai_render', 'tab_lookdev'),
    'MixieMoodboardTabLookdev360Props': ('texture_gen', 'tab_lookdev360'),
    'MixieMoodboardTabPBRGenProps': ('pbr_generation', 'tab_pbr_gen'),
    'MixieMoodboardTabImageTo3DProps': ('model_gen', 'tab_image_to_3d'),
    'MixieMoodboardTabMeshSegmentProps': ('mesh_segmentation', 'tab_mesh_segment'),
    'MixieMoodboardTabVideoGenProps': ('video_gen', 'tab_video_gen'),
    'MixieMoodboardTabVideoUpscaleProps': ('video_upscale', 'tab_video_upscale'),
    'MixieMoodboardTabWorldLabsProps': ('world_labs', 'tab_world_labs'),
    'MixieMoodboardTabSceneReconProps': ('scene_gen', 'tab_scene_recon'),
}
# Stable product actions, never operator arguments or arbitrary RNA strings.
ACTIONS = {
    'mixar.generations_add_asset': ('library', 'add_asset'),
    'mixar.generations_add_selected': ('library', 'add_selected'),
    'mixar.generations_select_media': ('library', 'open_media'),
    'mixar.generations_select_splat': ('library', 'open_splat'),
    'mixar.generations_add_library': ('library', 'connect_library'),
    'mixar.generations_remove_library': ('library', 'disconnect_library'),
    'mixie.moodboard_add_template': ('moodboard', 'add_template'),
    'mixie.moodboard_create_connected_action': ('moodboard', 'add_connected_node'),
    'mixie.moodboard_run_action_node': ('moodboard', 'run_node'),
    'mixie.moodboard_cancel_action_node': ('moodboard', 'cancel_node'),
    'mixie.moodboard_connect_nodes': ('moodboard', 'connect_nodes'),
    'mixie_chat.send_message': ('agent', 'send_message'),
}
_previous_tab = None
_tab_started = None
TAB_CAPABILITIES = {'THREE_D': 'model_gen', 'IMAGE': 'image_gen',
                    'VIDEO': 'video_gen', 'SPLAT': 'world_labs'}


def surface(context):
    area = getattr(getattr(context, 'area', None), 'type', '')
    return {'AGENT_BUBBLE': 'agent_island', 'MIXIE': 'moodboard',
            'VIEW_3D': 'viewport'}.get(area, 'other')


def reset_navigation():
    global _previous_tab, _tab_started
    _previous_tab, _tab_started = None, None


def tab_changed(context, tab):
    """Observe actual tab changes; origin distinguishes handoffs from clicks.

    First observation seeds silently. Dwell is elapsed time between changes,
    not attention time (the window may have been minimized).
    """
    global _previous_tab, _tab_started
    try:
        if tab not in TABS:
            return
        now = time.monotonic()
        previous, started = _previous_tab, _tab_started
        if previous == tab:
            return
        _previous_tab, _tab_started = tab, now
        from .draft_events import capture_draft_abandoned, note_panel_entered
        if previous in TAB_CAPABILITIES and is_enabled():
            capture_draft_abandoned(context, TAB_CAPABILITIES[previous], now - started,
                                    surface='agent_island')
        if tab in TAB_CAPABILITIES:
            note_panel_entered(TAB_CAPABILITIES[tab])
        if previous is None or not is_enabled():
            return
        capture(EVENT_ISLAND_TAB, {
            'tab': tab, 'previous_tab': previous,
            'previous_duration_seconds': round(max(0, now - started), 1),
            'origin_surface': surface(context),
        }, context=context)
    except Exception:
        pass


def operator_outcome(operator_id, result, context):
    """Semantic actions share the registration wrapper's one-shot boundary."""
    try:
        action = ACTIONS.get(operator_id)
        if not action:
            return
        outcome = ('error' if 'ERROR' in result else
                   'modal_started' if 'RUNNING_MODAL' in result else
                   'finished' if 'FINISHED' in result else 'cancelled')
        capture(EVENT_UI_ACTION, {
            'feature': action[0], 'action': action[1],
            'outcome': outcome, 'surface': surface(context),
        }, context=context)
    except Exception:
        pass


def generation_attempt(context, owner):
    """Return a bounded snapshot used by the matching dispatch result."""
    try:
        capability, attr = OWNERS.get(owner, ('unknown', ''))
        sidebar = getattr(context.scene, 'mixie_moodboard_sidebar', None)
        tab = getattr(sidebar, attr, None)
        prompt = getattr(tab, 'prompt', '') or ''
        from .draft_events import _prompt_bucket
        properties = {
            'attempt_id': str(uuid.uuid4()), 'capability': capability,
            'surface': surface(context), 'has_prompt': bool(prompt),
            'prompt_length_bucket': _prompt_bucket(prompt),
        }
        capture(EVENT_GENERATION_ATTEMPT, properties, context=context)
        return properties
    except Exception:
        return {}


def generation_dispatch(context, attempt, outcome):
    try:
        if outcome not in {'unknown_owner', 'unavailable', 'poll_failed',
                           'error', 'cancelled', 'modal_started', 'dispatched'}:
            return
        capture(EVENT_GENERATION_DISPATCH, {**attempt, 'outcome': outcome}, context=context)
    except Exception:
        pass
