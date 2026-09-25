"""A scene renamed mid-turn keeps its turn handler (plan row 1.9)."""

from _open_run_support import _scene, clean_state, live_bpy  # noqa: F401
from mixar.modules.space_mixie_chat.core import turn_transport as transport


def test_handler_follows_a_renamed_scene(live_bpy):
    scene = _scene(session_id='sid-rename')
    scene.name = 'Before'
    live_bpy.data.scenes.append(scene)
    handler = transport.create_turn_handler('Before')
    handler._session_id = 'sid-rename'
    scene.name = 'After'
    assert transport.get_turn_handler('After') is handler
    assert transport.get_turn_handler('Before') is None
    assert handler.scene_name == 'After' and 'Before' not in transport._handlers
    assert handler._scene() is scene
    transport.cleanup_turn_handler('After')
    assert not transport._handlers
