/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Socket and output-handle painters for the moodboard graph.
 *
 * Split out of #mixie_draw_moodboard_graph.cc (500-line rule): the socket
 * visual language — type colors, occupancy, labels — is one self-contained
 * vocabulary shared by action, asset, and media cards.
 */

#include "mixie_draw_moodboard_intern.hh"
#include "mixie_moodboard_socket_style.hh"

#include "BLI_string.h"
#include "DNA_theme_types.h"   /* UI_SCALE_FAC */
#include "DNA_userdef_types.h" /* extern UserDef U (used by UI_SCALE_FAC) */
#include "UI_interface_c.hh"

namespace blender::ed::mixie {

/* Type colors shared by input sockets and output handles, chosen to read on
 * both the black canvas and the dark card face. Which color a socket takes is
 * data-driven (its ``accepted_types``), so a new backend input type degrades
 * to neutral instead of misreporting. */
const float *moodboard_socket_type_color(const char *accepted_types)
{
  return socket_style::type_color(accepted_types ? accepted_types : "");
}

/* Output kind per ACTION_TYPES index. ORDER-PINNED to
 * ``moodboard_graph_properties.py``'s ACTION_TYPES and the output map in
 * ``node_schema.py`` (IMAGE_GEN, VIDEO_GEN, MODEL_3D, MASK_DETAIL, PBR_GEN,
 * RETOPOLOGY, MESH_SEGMENT, AUTO_RIG, VIDEO_UPSCALE, WORLD_LABS, CHARACTER_PARTS,
 * ASSEMBLE) — see tests/moodboard/test_node_ui_polish.py. */
static const char ACTION_OUTPUT_KINDS[] = {
    'I', 'V', 'M', 'I', 'M', 'M', 'M', 'M', 'V', 'S', 'M', 'M'};

const float *moodboard_action_output_color(const int action_type)
{
  if (action_type < 0 || action_type >= int(sizeof(ACTION_OUTPUT_KINDS))) {
    return socket_style::NEUTRAL;
  }
  switch (ACTION_OUTPUT_KINDS[action_type]) {
    case 'I':
      return socket_style::IMAGE;
    case 'V':
      return socket_style::VIDEO;
    case 'M':
      return socket_style::MESH;
    default:
      return socket_style::NEUTRAL;
  }
}

const float *moodboard_media_output_color(const Image *image)
{
  return (image && image->source == IMA_SRC_MOVIE) ? socket_style::VIDEO : socket_style::IMAGE;
}

const float *moodboard_mesh_output_color()
{
  return socket_style::MESH;
}

float moodboard_socket_radius_px(const View2D *v2d, const bool output)
{
  return socket_style::radius_px(ui::view2d_scale_get_x(v2d), UI_SCALE_FAC, output);
}

float moodboard_socket_hit_radius_px(const View2D *v2d, const bool output)
{
  return socket_style::hit_radius_px(ui::view2d_scale_get_x(v2d), UI_SCALE_FAC, output);
}

static float socket_zoom(const View2D *v2d)
{
  return std::max(ui::view2d_scale_get_x(v2d), 0.001f);
}

/** Filled geometry with a one-pixel feather keeps small circles smooth on Metal too. */
static void socket_disc(const uint pos,
                        const uint col,
                        const float x,
                        const float y,
                        const float radius,
                        const float feather,
                        const float color[3],
                        const float alpha = 1.0f)
{
  constexpr int segments = 48;
  const float inner = std::max(0.0f, radius - feather);
  immBegin(GPU_PRIM_TRI_FAN, segments + 2);
  immAttr4f(col, color[0], color[1], color[2], alpha);
  immVertex2f(pos, x, y);
  for (int i = 0; i <= segments; i++) {
    const float angle = 2.0f * float(M_PI) * i / segments;
    immAttr4f(col, color[0], color[1], color[2], alpha);
    immVertex2f(pos, x + inner * cosf(angle), y + inner * sinf(angle));
  }
  immEnd();
  immBegin(GPU_PRIM_TRI_STRIP, (segments + 1) * 2);
  for (int i = 0; i <= segments; i++) {
    const float angle = 2.0f * float(M_PI) * i / segments;
    const float dx = cosf(angle), dy = sinf(angle);
    immAttr4f(col, color[0], color[1], color[2], alpha);
    immVertex2f(pos, x + inner * dx, y + inner * dy);
    immAttr4f(col, color[0], color[1], color[2], 0.0f);
    immVertex2f(pos, x + radius * dx, y + radius * dy);
  }
  immEnd();
}

/** Dark input bodies distinguish a connected center pip from an empty ring. */
void moodboard_draw_socket(View2D *v2d,
                           const float x,
                           const float y,
                           const float color[3],
                           const bool connected,
                           const bool required,
                           const float radius_px)
{
  const float zoom = socket_zoom(v2d), unit = UI_SCALE_FAC / zoom;
  const float radius = radius_px / zoom, feather = 1.0f / zoom;
  const float rim = std::min(radius * 0.3f, (required ? 1.8f : 1.25f) * unit);
  const float body[3] = {0.055f, 0.067f, 0.078f};
  const GPUBlend previous_blend = GPU_blend_get();
  GPU_blend(GPU_BLEND_ALPHA);
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(
      format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  const uint col = GPU_vertformat_attr_add(
      format, "color", blender::gpu::VertAttrType::SFLOAT_32_32_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_SMOOTH_COLOR);
  socket_disc(pos, col, x, y, radius, feather, color, required || connected ? 1.0f : 0.75f);
  socket_disc(pos, col, x, y, radius - rim, feather, body);
  if (connected) {
    socket_disc(pos, col, x, y, radius * 0.40f, feather, color);
  }
  immUnbindProgram();
  GPU_blend(previous_blend);
}

void moodboard_draw_output_handle(View2D *v2d, const float x, const float y, const float color[3])
{
  const float zoom = socket_zoom(v2d), unit = UI_SCALE_FAC / zoom;
  const float radius = moodboard_socket_radius_px(v2d, true) / zoom;
  const float body[3] = {0.055f, 0.067f, 0.078f};
  const GPUBlend previous_blend = GPU_blend_get();
  GPU_blend(GPU_BLEND_ALPHA);
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(
      format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  const uint col = GPU_vertformat_attr_add(
      format, "color", blender::gpu::VertAttrType::SFLOAT_32_32_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_SMOOTH_COLOR);
  socket_disc(pos, col, x, y, radius, 1.0f / zoom, color);
  socket_disc(pos, col, x, y, radius - 1.4f * unit, 1.0f / zoom, body);
  /* Filled rectangles keep the plus crisp without platform-dependent wide lines. */
  const float arm = radius * 0.40f, half_stroke = 0.65f * unit;
  immBegin(GPU_PRIM_TRIS, 12);
  const float bars[2][4] = {{x - arm, y - half_stroke, x + arm, y + half_stroke},
                            {x - half_stroke, y - arm, x + half_stroke, y + arm}};
  for (const auto &bar : bars) {
    const float vertices[6][2] = {{bar[0], bar[1]},
                                  {bar[2], bar[1]},
                                  {bar[2], bar[3]},
                                  {bar[0], bar[1]},
                                  {bar[2], bar[3]},
                                  {bar[0], bar[3]}};
    for (const auto &vertex : vertices) {
      immAttr4f(col, 0.90f, 0.94f, 0.96f, 1.0f);
      immVertex2fv(pos, vertex);
    }
  }
  immEnd();
  immUnbindProgram();
  GPU_blend(previous_blend);
}

static float socket_label_font_size(View2D *v2d)
{
  const float zoom = socket_zoom(v2d);
  return std::clamp(13.0f * zoom, 10.0f * UI_SCALE_FAC, 12.0f * UI_SCALE_FAC) / zoom;
}

/** Right-aligned socket name beside a selected node's input, so what each
 * socket accepts is readable before a noodle is committed to it. */
float moodboard_socket_label_width(View2D *v2d, const char *label)
{
  const int font_id = BLF_default();
  BLF_size(font_id, socket_label_font_size(v2d));
  return BLF_width(font_id, label, strlen(label));
}

void moodboard_draw_socket_label(View2D *v2d,
                                 PointerRNA *socket,
                                 const float socket_x,
                                 const float socket_y,
                                 const float radius_px)
{
  char label[MIXIE_GRAPH_LABEL_BUF];
  mixie_rna_string_get_clamped(socket, "label", label, sizeof(label));
  if (!label[0]) {
    return;
  }
  const int font_id = BLF_default();
  const float width = moodboard_socket_label_width(v2d, label);
  const float zoom = socket_zoom(v2d), unit = UI_SCALE_FAC / zoom;
  const float font_size = socket_label_font_size(v2d);
  const float gap = (radius_px + 6.0f * UI_SCALE_FAC) / zoom;
  /* Incoming links share the label's baseline. An opaque, quiet bed keeps
   * them from striking through the text while preserving the terminal stub. */
  const rctf backing = {socket_x - gap - width - 3.0f * unit,
                        socket_x - gap + 3.0f * unit,
                        socket_y - font_size * 0.5f - unit,
                        socket_y + font_size * 0.5f + unit};
  const float background[4] = {0.025f, 0.030f, 0.035f, 1.0f};
  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  ui::draw_roundbox_4fv(&backing, true, 2.0f * unit, background);
  BLF_color4f(font_id, 0.78f, 0.82f, 0.86f, 0.95f);
  BLF_position(
      font_id, socket_x - gap - width, socket_y - font_size * 0.35f, 0.0f);
  BLF_draw(font_id, label, strlen(label));
}

}  // namespace blender::ed::mixie
