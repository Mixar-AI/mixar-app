# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Export sheet's layout (`mixar.export_menu`'s draw()).

The same native sheet as AI Provider settings and Connect MCP
(`common/sheet/kit`), wider in its sidebar: the title over the header
divider, the format tiles grouped by section on the left (a `TILE` sheet
element: icon over label, the picked one lit), and on the right the file
name, the quality, the picked format's settings and one action at the foot.

The one-action contract: every state marks exactly ONE button as the
dialog's default, which keeps the props dialog's OK/Cancel row away. Export
is a confirm (it closes the sheet and runs `mixar.export_menu_run`); Web
publishes in place so its progress and link show here. This module only
draws; state lives on ``wm.mixar_export_menu``.
"""

from mixar.modules.common.i18n import iface_, n_
from mixar.modules.common.sheet import kit as S

from ...constants import (
    BY_KEY,
    ENGINE_FORMAT_ITEMS,
    GLTF_ITEMS,
    IMAGE_FORMAT_ITEMS,
    KIND_IMAGE,
    KIND_MODEL,
    KIND_PROJECT,
    KIND_VIDEO,
    KIND_WEB,
    QUALITY_ITEMS,
    SECTIONS,
    TILES_PER_ROW,
    VIDEO_FORMAT_ITEMS,
)
from ...core import runner

OP_PICK = "mixar.export_menu_pick"
OP_OPTION = "mixar.export_menu_option"
OP_TOGGLE = "mixar.export_menu_toggle"
OP_RUN = "mixar.export_menu_run"
OP_PUBLISH = "mixar.export_menu_publish"
OP_BROWSE = "mixar.export_menu_browse"
TILE_KIND = "TILE"
CHIP_GREEN = 1.0  # a lit chip fills Mixar green (the painter's `chip_green`)

# Geometry (design px, 2x): the kit's width with a wider sidebar for tiles.
SHEET_WIDTH = S.WIDTH // 2
SIDEBAR = 620
SPLIT_FACTOR = (SIDEBAR / 2) / (S.WIDTH / 2 - S.SPLIT_SPACE / 2)
RIGHT_W = S.WIDTH - SIDEBAR - S.SPLIT_SPACE
TEXT_W = RIGHT_W - S.RIGHT_INSET - S.RIGHT_MARGIN
TILE = 116
TILE_GAP = 18
SECTION_GAP = 28
BLOCK_GAP = 28
BODY_BOTTOM = 64
FOOT = S.NOTE_H + S.NOTE_TO_INPUT + S.INPUT_H + S.BOTTOM
EXPORT_TEXT = n_("Export scene!")


def _chunks(keys, size):
    return [keys[i:i + size] for i in range(0, len(keys), size)]


def body_height():
    """The sidebar's height under the header; the right column matches it."""
    height = BODY_BOTTOM
    for index, (_caption, keys) in enumerate(SECTIONS):
        rows = len(_chunks(keys, TILES_PER_ROW))
        height += (S.CAPTION_TOP if index == 0 else SECTION_GAP) + S.CAPTION_H
        height += S.CAPTION_TO_ROWS + rows * TILE + (rows - 1) * TILE_GAP
    return height


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def draw_sheet(layout, context, logo_icon):
    """``logo_icon(key)`` is the engine logo's preview icon id (0: none)."""
    layout.use_property_split = False
    layout.use_property_decorate = False
    props = context.window_manager.mixar_export_menu

    sheet = layout.column(align=True)
    if hasattr(sheet, 'mixar_sheet_frame'):
        sheet.mixar_sheet_frame(header=S.HEADER, sidebar=SIDEBAR)
    _draw_header(sheet)

    height = body_height()
    body = sheet.split(factor=SPLIT_FACTOR, align=True)
    _draw_tiles(S.fixed(body.column(align=True), height), props, logo_icon)
    right = S.fixed(body.column(align=True), height)
    if BY_KEY[props.format].kind == KIND_WEB:
        _draw_web(right, context, height)
    else:
        _draw_export(right, context, props, height)


def _draw_header(sheet):
    header = sheet.row(align=True)
    title = header.row(align=True)
    title.scale_y = S.units(S.HEADER)
    S.label(title, iface_("Export your masterpiece!") + "\n"
            + iface_("Pick a format, name the file and export it."), S.TITLE, translate=False)
    slot = S.sized(header, S.CLOSE)
    slot.scale_y = S.units(S.CLOSE_TOP + S.CLOSE)
    S.dismiss(slot, S.CLOSE_GLYPH, S.CLOSE_KIND)
    S.gap(header, S.CLOSE_RIGHT)


# ---------------------------------------------------------------------------
# Sidebar: the tiles
# ---------------------------------------------------------------------------

def _tile(line, key, lit, logo_icon):
    fmt = BY_KEY[key]
    text = iface_(fmt.label) if fmt.translate else fmt.label
    slot = S.sized(line, TILE)
    logo = logo_icon(fmt.use_case) if not fmt.icon else 0
    if logo:
        props = slot.operator(OP_PICK, text=text, translate=False, icon_value=logo)
    else:
        props = slot.operator(OP_PICK, text=text, translate=False, icon=fmt.icon or 'FILE_3D')
    props.format = key
    if hasattr(slot, 'mixar_sheet_label'):
        S.tag(slot, TILE_KIND, lit=lit)


def _draw_tiles(col, props, logo_icon):
    for index, (caption, keys) in enumerate(SECTIONS):
        S.sep(col, S.CAPTION_TOP if index == 0 else SECTION_GAP)
        S.label(S.row(col, S.CAPTION_H, left=S.LEFT_INSET, right=S.ROW_RIGHT), caption,
                S.CAPTION)
        S.sep(col, S.CAPTION_TO_ROWS)
        for row_index, chunk in enumerate(_chunks(keys, TILES_PER_ROW)):
            if row_index:
                S.sep(col, TILE_GAP)
            line = S.row(col, TILE, left=S.LEFT_INSET, packed=True)
            for tile_index, key in enumerate(chunk):
                if tile_index:
                    S.gap(line, TILE_GAP)
                _tile(line, key, key == props.format, logo_icon)


# ---------------------------------------------------------------------------
# Right column: shared rows
# ---------------------------------------------------------------------------

def _caption(col, text, first=False):
    S.sep(col, S.CAPTION_TOP if first else BLOCK_GAP)
    S.caption(col, text, S.RIGHT_INSET)
    S.sep(col, S.CAPTION_TO_CHIPS)


def _chips(col, name, items, current, enabled=True):
    """A segmented row of chips: one ``(key, label, _)`` item each; the lit
    chip is ``current``. Labels are UI text (translated here)."""
    line = S.row(col, S.CHIP_H, left=S.RIGHT_INSET, right=S.RIGHT_MARGIN, packed=True)
    line.enabled = enabled
    for key, label, _tip in items:
        text = iface_(label)
        slot = S.sized(line, S.text_width(line, S.CHIP, text) + 2 * S.CHIP_PAD)
        S.choice(slot, OP_OPTION, text, S.CHIP, lit=key == current, extra=CHIP_GREEN,
                 name=name, value=key)


def _switch(col, name, text, on, enabled=True):
    line = S.row(col, S.STRIP_H, left=S.RIGHT_INSET, right=S.RIGHT_MARGIN)
    line.enabled = enabled
    S.switch(line, OP_TOGGLE, text, on).name = name


def _note(col, text, kind=S.NOTE):
    for chunk in S.wrap(col, kind, text, TEXT_W) or [text]:
        S.label(S.row(col, S.NOTE_H, left=S.RIGHT_INSET, right=S.RIGHT_MARGIN), chunk, kind,
                translate=False)


def _notes_height(col, text, kind=S.NOTE):
    return S.NOTE_H * max(1, len(S.wrap(col, kind, text, TEXT_W)))


# ---------------------------------------------------------------------------
# Right column: files, images and videos
# ---------------------------------------------------------------------------

def _draw_file_path(col, props):
    """The full path, editable, with Browse docked inside the field."""
    _caption(col, n_("FILE PATH"), first=True)
    line = S.row(col, S.INPUT_H, left=S.RIGHT_INSET, right=S.RIGHT_MARGIN)
    text = iface_("Browse")
    browse_w = S.text_width(line, S.SECONDARY, text) + S.BUTTON_PAD + S.DOCK_INSET
    S.input_field(S.sized(line, TEXT_W - browse_w), props, "file_path", docked_w=browse_w)
    S.button(S.sized(line, browse_w), OP_BROWSE, text, S.SECONDARY, docked=True)


def _resolution(context, props):
    options = runner.render_options(props, context, BY_KEY[props.format].kind)
    return options["width"], options["height"]


def _draw_settings(col, context, props):
    fmt = BY_KEY[props.format]
    kind = fmt.kind
    _caption(col, n_("SETTINGS"))
    if kind == KIND_PROJECT:
        _switch(col, "strip_chat", iface_("Leave out the agent chat"), props.strip_chat)
        _note(col, iface_(".mixar opens in Mixar; .blend also opens in Blender.")
              if props.format == "MIXAR" else
              iface_("A copy of this file; the scene you have open is not changed."))
        return
    if kind == KIND_IMAGE:
        _chips(col, "image_format", IMAGE_FORMAT_ITEMS, props.image_format)
        S.sep(col, S.GAP)
        width, height = _resolution(context, props)
        _note(col, iface_("Renders the scene camera at {width} × {height}.").format(
            width=width, height=height))
        return
    if kind == KIND_VIDEO:
        _chips(col, "video_format", VIDEO_FORMAT_ITEMS, props.video_format)
        S.sep(col, S.GAP)
        scene = context.scene
        width, height = _resolution(context, props)
        fps = scene.render.fps / (scene.render.fps_base or 1.0)
        _note(col, iface_("Frames {start}–{end} at {fps} fps, {width} × {height}.").format(
            start=scene.frame_start, end=scene.frame_end, fps=round(fps, 2),
            width=width, height=height))
        return
    # Models: the glTF flavour or the engine's file type, then the scope.
    if props.format == "GLB":
        _chips(col, "gltf_variant", GLTF_ITEMS, props.gltf_variant)
        S.sep(col, S.GAP)
    elif fmt.use_case in ("unreal", "unity"):
        _chips(col, "engine_format", ENGINE_FORMAT_ITEMS, props.engine_format)
        S.sep(col, S.GAP)
    _switch(col, "selected_only", iface_("Selected objects only"), props.selected_only)
    if props.format == "OBJ":
        _note(col, iface_("OBJ is static: rigs and animation are left out."))
    else:
        _switch(col, "include_animation", iface_("Include animation"), props.include_animation)
    if fmt.use_case in ("unreal", "unity"):
        _note(col, iface_("Scale, axes and smoothing are set up for {engine}.").format(
            engine=fmt.label))


def _draw_export(col, context, props, height):
    kind = BY_KEY[props.format].kind
    top = S.fixed(col, height - FOOT)
    _draw_file_path(top, props)
    _caption(top, n_("QUALITY"))
    renders = kind in (KIND_IMAGE, KIND_VIDEO)
    _chips(top, "quality", QUALITY_ITEMS, props.quality, enabled=renders)
    if not renders:
        _note(top, iface_("Quality sets how images and videos render; files keep "
                          "the scene's full detail."))
    _draw_settings(top, context, props)

    cached = runner.view()
    reason = cached["blocker"]
    line = S.row(col, S.NOTE_H, left=S.RIGHT_INSET, right=S.RIGHT_MARGIN)
    if reason:
        S.label(line, iface_(reason), S.DANGER_TEXT, translate=False)
    elif cached["taken"]:
        S.label(line, iface_("That file exists; this saves as {name}").format(
            name=cached["name"]), S.NOTE, translate=False)
    else:
        S.label(line, iface_("Saves as {name}").format(name=cached["name"]), S.NOTE,
                translate=False)
    S.sep(col, S.NOTE_TO_INPUT)
    foot = S.row(col, S.INPUT_H, left=S.RIGHT_INSET, right=S.RIGHT_MARGIN, align='RIGHT')
    text = iface_(EXPORT_TEXT)
    slot = S.sized(foot, max(S.SAVE_W, S.text_width(foot, S.PRIMARY, text) + 2 * S.BUTTON_PAD))
    slot.enabled = not reason
    S.confirm(slot, OP_RUN, text, S.PRIMARY, default=True)
    S.sep(col, S.BOTTOM)


# ---------------------------------------------------------------------------
# Right column: Publish to Web
# ---------------------------------------------------------------------------

def _web_state(context):
    from mixar.modules.web_publish.core.publish_state import get_publish_state
    state = get_publish_state()
    progress, _ = state.snapshot()
    return state, progress, state.scene_name == context.scene.name


def _foot_button(col, operator_id, text, kind=S.PRIMARY, enabled=True):
    foot = S.row(col, S.INPUT_H, left=S.RIGHT_INSET, right=S.RIGHT_MARGIN, align='RIGHT')
    slot = S.sized(foot, max(S.SAVE_W, S.text_width(foot, kind, text) + 2 * S.BUTTON_PAD))
    slot.enabled = enabled
    return S.button(slot, operator_id, text, kind, default=True)


def _draw_web(col, context, height):
    from mixar.modules.web_publish.core.publish_state import (
        STATUS_CANCELLED, STATUS_ERROR, format_message,
    )
    web = getattr(context.scene, "mixar_web_publish", None)
    top = S.fixed(col, height - (S.NOTE_TO_INPUT + S.INPUT_H + S.BOTTOM))
    if web is None:
        _caption(top, n_("PUBLISH TO WEB"), first=True)
        _note(top, iface_("Publish to Web is not available in this build."), S.DANGER_TEXT)
        S.sep(col, S.NOTE_TO_INPUT)
        _foot_button(col, OP_PUBLISH, iface_("Publish to Web"), enabled=False)
        S.sep(col, S.BOTTOM)
        return
    state, progress, mine = _web_state(context)
    if state.busy:
        _caption(top, n_("PUBLISHING"), first=True)
        _note(top, iface_("Exporting and uploading this scene…") if mine
              else iface_("Publishing another scene…"), S.BODY)
        if mine and progress.detail:
            _note(top, format_message(iface_(progress.detail), progress.detail_args))
        S.sep(col, S.NOTE_TO_INPUT)
        _foot_button(col, "mixar.web_publish_cancel", iface_("Cancel"), S.SECONDARY,
                     enabled=mine)
        S.sep(col, S.BOTTOM)
        return
    if mine and progress.status in (STATUS_ERROR, STATUS_CANCELLED):
        _caption(top, n_("PUBLISH TO WEB"), first=True)
        _note(top, iface_("Publish cancelled") if progress.status == STATUS_CANCELLED
              else format_message(iface_(progress.error), progress.error_args), S.DANGER_TEXT)
    elif web.is_published:
        _caption(top, n_("LIVE"), first=True)
        line = S.row(top, S.STRIP_H, left=S.RIGHT_INSET, right=S.RIGHT_MARGIN)
        S.status_dot(line, S.STATUS_ON)
        S.label(line, iface_("Live · version {revision}").format(revision=web.revision),
                S.BODY, translate=False)
        S.sep(top, S.GAP)
        S.snippet(top, [web.link], left=S.RIGHT_INSET, right=S.RIGHT_MARGIN,
                  dock=("mixar.web_publish_copy_link", iface_("Copy link")))
        S.sep(top, S.GAP)
        line = S.row(top, S.BUTTON_H, left=S.RIGHT_INSET, right=S.RIGHT_MARGIN, packed=True)
        text = iface_("Open in Browser")
        S.button(S.sized(line, S.text_width(line, S.SECONDARY, text) + 2 * S.BUTTON_PAD),
                 "mixar.web_publish_open", text, S.SECONDARY)
    else:
        _caption(top, n_("PUBLISH TO WEB"), first=True)
        _note(top, iface_("A shareable link to an explorable 3D website of this scene."),
              S.BODY)
    _caption(top, n_("TITLE"))
    S.input_field(S.row(top, S.FIELD_H, left=S.RIGHT_INSET, right=S.RIGHT_MARGIN),
                  web, "title")
    _caption(top, n_("ACCESS"))
    S.dropdown(S.row(top, S.FIELD_H, left=S.RIGHT_INSET, right=S.RIGHT_MARGIN), web,
               "visibility")
    S.sep(top, S.GAP)
    _switch(top, "web_include_animation", iface_("Include animation"), web.include_animation)

    S.sep(col, S.NOTE_TO_INPUT)
    update = web.is_published
    _foot_button(col, OP_PUBLISH, iface_("Publish new version") if update
                 else iface_("Publish to Web")).update_existing = update
    S.sep(col, S.BOTTOM)


# Auto-discovery imports every file under ui/ — nothing to register here.
classes = ()
