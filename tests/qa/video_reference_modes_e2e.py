#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit Video-only references: native pickers, tabs, removal and Send.

Run on an isolated offline Dev QA app with a cached generation catalog.
Requires ffmpeg for a disposable movie fixture. QA_CATALOG_FIXTURE can point
to a previously cached catalog JSON for offline Splat/Video controls. QA_HARNESS, MIXAR_QA_PORT and
QA_SCENARIO_OUT select the harness, app and local-only evidence directory.
Only the chat transport is probed; no generation or backend request is sent.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

from PIL import Image

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
from generation_reference_column_e2e import TABS, capture
from reference_drop_ux_e2e import SCENE, batch_drop, pause

VIDEO_UPLOAD = 'MIXAR_OT_pane_video_upload_reference'
OTHER_UPLOADS = {
    'AGENT': 'MIXIE_CHAT_OT_add_image_from_file',
    'IMAGE': 'MIXIE_OT_imagegen_upload_reference',
    'THREE_D': 'MIXIE_OT_image_to_3d_pick_image',
    'SPLAT': 'MIXIE_OT_world_labs_pick_image',
}


def tab(qa, key):
    qa.eval('result=str(bpy.ops.mixar.bubble_restore())')
    pause(qa)  # Restore may animate/re-seat the window before header hit testing.
    qa.click(area_type='AGENT_BUBBLE', text=TABS[key])
    qa.wait(f'bpy.context.window_manager.mixar_bubble_tab=={key!r}', timeout=5)
    pause(qa)


def picker(qa, out, op, path, *, video=False, confirm=True):
    qa.click(area_type='AGENT_BUBBLE', op=op)
    qa.wait("bool(drv.find(area_type='FILE_BROWSER',prop='directory'))", timeout=8)
    selected = qa.eval("h=drv.find(area_type='FILE_BROWSER',prop='directory')[0]\n"
                       "p=h['_area'].spaces.active.params\n"
                       f"p.directory={str(path.parent).encode()!r}\np.filename={path.name!r}\n"
                       "result={'glob':p.filter_glob,'movies':p.use_filter_movie}")
    glob = selected['glob'].lower()
    assert ('*.mp4' in glob) == video, selected
    assert '*.png' in glob, selected
    # Commit the native field to finish File Browser directory navigation;
    # assigning RNA alone leaves its asynchronous file list at Loading.
    qa.click(area_type='FILE_BROWSER', prop='directory')
    window = qa.find(area_type='FILE_BROWSER', prop='directory')['widgets'][0]['window']
    qa.press('RET', window=window)
    pause(qa, 1.5)
    qa.cmd('snap', path=str(out/f'picker-{op}.png'),
           target={'area_type':'FILE_BROWSER','prop':'directory'}, margin=1600)
    qa.click(area_type='FILE_BROWSER', op='FILE_OT_execute' if confirm else 'FILE_OT_cancel')
    qa.wait("not drv.find(area_type='FILE_BROWSER')", timeout=8)
    pause(qa)


def references(qa):
    return [w['text'] for w in qa.find(surface='reference_preview')['widgets']]


def non_video_mode(qa, out, mode, movie):
    tab(qa, mode)
    assert movie.name not in references(qa), (mode, references(qa))
    assert qa.eval(f"result=all(a.image_path!={movie.name!r} "
                   f"for a in {SCENE}.mixie_chat_pending_attachments)")
    capture(qa, out, mode.lower()+'-no-video')
    # The test movie has saturated magenta bars; the UI has no magenta. This
    # also catches old footer previews outside the exported reference column.
    with Image.open(out/(mode.lower()+'-no-video.png')) as frame:
        movie_pixels = sum(r > 180 and b > 180 and g < 80
                           for r, g, b in frame.convert('RGB').getdata())
    assert movie_pixels == 0, (mode, movie_pixels, 'Movie leaked into a fallback preview')
    picker(qa, out, OTHER_UPLOADS[mode], movie, confirm=False)
    # Bypass the filter by explicitly entering the movie filename. Even that
    # must not create an image reference or turn the movie into a still frame.
    picker(qa, out, OTHER_UPLOADS[mode], movie)
    popups = qa.find(popup=True)['widgets']
    if popups:
        qa.press('ESC', window=popups[0]['window'])
        qa.wait('not drv.find(popup=True)', timeout=5)
    pause(qa)
    assert movie.name not in references(qa), (mode, references(qa))
    assert qa.eval(f'result=not {SCENE}.mixie_chat_pending_attachments')


def restored_draft(qa, out, movie):
    tab(qa, 'AGENT')
    qa.cmd('set_text', widget={'area_type':'AGENT_BUBBLE','prop':'mixie_chat_input'},
           text='Keep this draft while I remove the video', enter=False)
    for source, path in [('BLEND_DATA', movie.name), ('FILE', str(movie))]:
        qa.eval(f"a={SCENE}.mixie_chat_pending_attachments.add()\n"
                f"a.image_path={path!r}\na.image_source={source!r}\na.display_name={movie.name!r}\n"
                "from mixar.modules.space_mixie_chat.core.ui_utils import redraw_chat_areas\n"
                "redraw_chat_areas()\nresult=True")
        qa.wait("bool(drv.find(surface='reference_preview'))", timeout=6)
        result = qa.eval("from mixar.modules.space_mixie_chat.core.composer_send import can_send\n"
                         f"result=can_send({SCENE})")
        assert result[0] is False and 'Video mode' in result[1], result
        # Clicking the native disabled action cannot create a user message.
        qa.click(area_type='AGENT_BUBBLE', op='MIXIE_CHAT_OT_send_message')
        assert qa.eval('import chat_send_probe as probe; result=len(probe.calls)') == 0
        assert qa.eval(f'result={SCENE}.mixie_chat_input') == 'Keep this draft while I remove the video'
        capture(qa, out, 'blocked-'+source.lower())
        qa.click(area_type='AGENT_BUBBLE', op='MIXIE_CHAT_OT_remove_attachment')
        qa.wait(f'not {SCENE}.mixie_chat_pending_attachments', timeout=5)
    assert qa.eval(f'from mixar.modules.space_mixie_chat.core.composer_send import can_send; result=can_send({SCENE})[0]') is True


def from_blend_rejection(qa, movie):
    result = qa.eval("from mixar.modules.space_mixie_chat.core.image_utils import get_blend_images\n"
                     f"assert {movie.name!r} not in [i['name'] for i in get_blend_images()]\n"
                     "h=drv.find(area_type='AGENT_BUBBLE',text='Agent chat')[0]\n"
                     "with bpy.context.temp_override(window=h['_win']):\n"
                     f"    status=bpy.ops.mixie_chat.add_image_from_blend(dropped_image_name={movie.name!r})\n"
                     "result=list(status)")
    assert result == ['CANCELLED'], result
    assert qa.eval(f'result=not {SCENE}.mixie_chat_pending_attachments')


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/video-reference-modes')).resolve()
    out.mkdir(parents=True, exist_ok=True)
    fixtures = out/'fixtures'
    fixtures.mkdir(exist_ok=True)
    movie = fixtures/'reference-video.mp4'
    still = fixtures/'reference-image.png'
    Image.new('RGB', (320, 180), '#508678').save(still)
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y',
                    '-f','lavfi','-i','testsrc2=size=320x180:rate=12','-t','1',
                    '-c:v','libx264','-pix_fmt','yuv420p',str(movie)], check=True)
    qa.wait("bpy.types.Operator.bl_rna_get_subclass_py('MIXAR_OT_pane_video_upload_reference') is not None",
            timeout=30)
    qa.eval("import os, sys\nassert os.environ.get('MIXAR_QA')=='1'\n"
            "from mixar.config import get_config\n"
            "assert get_config()['backend_url'].startswith('http://127.0.0.1:')\n"
            f"assert not {SCENE}.mixie_moodboard_images, 'Use a fresh isolated QA scene'\n"
            f"sys.path.insert(0,{str(Path(__file__).resolve().parent)!r})\n"
            "import chat_send_probe as probe\nprobe.install()\nresult=True")
    try:
        catalog_path = os.environ.get('QA_CATALOG_FIXTURE')
        qa.eval("from mixar.bootstrap import generation_catalog_cache as c\n"
                "from mixar.bootstrap.generation_catalog import storage, consumers\n"
                + (f"import json\nstorage.save(None,json.load(open({catalog_path!r}))['data'])\n"
                   "assert c._load_from_disk()\n" if catalog_path else "assert c.is_loaded()\n")
                + "consumers.notify_catalog_swapped()\nresult=True")
        tab(qa, 'VIDEO')
        qa.step('video-native-picker-and-import', picker, qa, out, VIDEO_UPLOAD, movie, video=True)
        qa.wait(f'{movie.name!r} in [w["text"] for w in drv.find(surface="reference_preview")]', timeout=8)
        capture(qa, out, 'video-preview')
        inputs = qa.eval("from mixar.modules.moodboard.core.media_utils import get_selected_moodboard_media_inputs\n"
                         "from types import SimpleNamespace\n"
                         f"result=get_selected_moodboard_media_inputs(SimpleNamespace(scene={SCENE}), fresh=True)")
        assert len(inputs['videos']) == 1 and not inputs['images'], inputs
        assert inputs['all_video_sources_available'], inputs
        for mode in OTHER_UPLOADS:
            qa.step(mode.lower()+'-excludes-videos', non_video_mode, qa, out, mode, movie)
        tab(qa, 'VIDEO')
        assert movie.name in references(qa), references(qa)
        qa.step('video-also-accepts-stills', picker, qa, out, VIDEO_UPLOAD, still, video=True)
        qa.wait("len(drv.find(surface='reference_preview'))==2", timeout=6)
        capture(qa, out, 'video-image-and-movie')
        assert references(qa)[0] == movie.name
        qa.click(area_type='AGENT_BUBBLE', op='MIXAR_OT_pane_remove_reference')
        qa.wait(f'not any(i.selected and i.image.source=="MOVIE" for i in {SCENE}.mixie_moodboard_images)', timeout=5)
        assert references(qa) == [still.name], references(qa)
        qa.click(area_type='AGENT_BUBBLE', op='MIXAR_OT_pane_remove_reference')
        qa.wait("not drv.find(surface='reference_preview')", timeout=5)
        tab(qa, 'AGENT')
        qa.wait(f'not {SCENE}.mixie_chat_pending_attachments', timeout=5)
        qa.step('agent-native-video-drop-refused', batch_drop, qa, [movie], chat=True)
        assert qa.eval(f'result=not {SCENE}.mixie_chat_pending_attachments')
        qa.step('agent-from-blend-refused', from_blend_rejection, qa, movie)
        qa.step('restored-video-drafts-cannot-send', restored_draft, qa, out, movie)
        assert qa.eval('import chat_send_probe as probe; result=len(probe.calls)') == 0
        verdict = {'video_picker':True,'video_preview':True,'non_video_modes':list(OTHER_UPLOADS),
                   'movie_removal':True,'agent_send_guard':True,'backend_calls':0}
        (out/'verdict.json').write_text(json.dumps(verdict, indent=2)+'\n')
        return verdict
    finally:
        qa.eval('import chat_send_probe as probe; probe.uninstall(); result=True')


if __name__ == '__main__':
    run_scenario('video_reference_modes_e2e', run)
