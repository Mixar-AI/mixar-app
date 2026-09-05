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

#include "BLI_string.h"

#include "GPU_immediate_util.hh"

namespace blender::ed::mixie {

/* Type colors shared by input sockets and output handles, chosen to read on
 * both the black canvas and the dark card face. Which color a socket takes is
 * data-driven (its ``accepted_types``), so a new backend input type degrades
 * to neutral instead of misreporting. */
static const float SOCKET_COLOR_IMAGE[3] = {0.92f, 0.68f, 0.29f};   /* amber */
static const float SOCKET_COLOR_VIDEO[3] = {0.41f, 0.64f, 0.94f};   /* blue */
static const float SOCKET_COLOR_MESH[3] = {0.36f, 0.80f, 0.63f};    /* green */
static const float SOCKET_COLOR_MIXED[3] = {0.74f, 0.57f, 0.89f};   /* violet */
static const float SOCKET_COLOR_NEUTRAL[3] = {0.56f, 0.57f, 0.60f}; /* gray */

const float *moodboard_socket_type_color(const char *accepted_types)
{
  if (!accepted_types || accepted_types[0] == '\0') {
    return SOCKET_COLOR_NEUTRAL;
  }
  if (strstr(accepted_types, "MESH")) {
    return SOCKET_COLOR_MESH;
  }
  const bool image = strstr(accepted_types, "IMAGE") != nullptr;
  const bool video = strstr(accepted_types, "VIDEO") != nullptr;
  if (image && video) {
    return SOCKET_COLOR_MIXED;
  }
  if (video) {
    return SOCKET_COLOR_VIDEO;
  }
  if (image) {
    return SOCKET_COLOR_IMAGE;
  }
  return SOCKET_COLOR_NEUTRAL;
}

/* Output kind per ACTION_TYPES index. ORDER-PINNED to
 * ``moodboard_graph_properties.py``'s ACTION_TYPES and the output map in
 * ``node_schema.py`` (IMAGE_GEN, VIDEO_GEN, MODEL_3D, MASK_DETAIL, PBR_GEN,
 * RETOPOLOGY, MESH_SEGMENT, AUTO_RIG) — see
 * tests/moodboard/test_node_ui_polish.py. */
static const char ACTION_OUTPUT_KINDS[] = {'I', 'V', 'M', 'I', 'M', 'M', 'M', 'M'};

const float *moodboard_action_output_color(const int action_type)
{
  if (action_type < 0 || action_type >= int(sizeof(ACTION_OUTPUT_KINDS))) {
    return SOCKET_COLOR_NEUTRAL;
  }
  switch (ACTION_OUTPUT_KINDS[action_type]) {
    case 'I':
      return SOCKET_COLOR_IMAGE;
    case 'V':
      return SOCKET_COLOR_VIDEO;
    case 'M':
      return SOCKET_COLOR_MESH;
    default:
      return SOCKET_COLOR_NEUTRAL;
  }
}

const float *moodboard_media_output_color(const Image *image)
{
  return (image && image->source == IMA_SRC_MOVIE) ? SOCKET_COLOR_VIDEO : SOCKET_COLOR_IMAGE;
}

const float *moodboard_mesh_output_color()
{
  return SOCKET_COLOR_MESH;
}

/**
 * One input socket. A connected socket is a filled type-colored disc; an empty
 * one is a hollow ring (louder when required) — so what still needs wiring is
 * visible at a glance. Every socket sits on a dark backplate so it stays
 * legible over links, the card edge, and the canvas alike.
 */
void moodboard_draw_socket(const float x,
                           const float y,
                           const float color[3],
                           const bool connected,
                           const bool required)
{
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(
      format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4f(0.05f, 0.05f, 0.06f, 0.95f);
  imm_draw_circle_fill_2d(pos, x, y, MOODBOARD_GRAPH_SOCKET_RADIUS + 2.5f, 24);
  if (connected) {
    immUniformColor4f(color[0], color[1], color[2], 1.0f);
    imm_draw_circle_fill_2d(pos, x, y, MOODBOARD_GRAPH_SOCKET_RADIUS, 24);
  }
  else {
    immUniformColor4f(0.10f, 0.10f, 0.11f, 1.0f);
    imm_draw_circle_fill_2d(pos, x, y, MOODBOARD_GRAPH_SOCKET_RADIUS, 24);
    immUniformColor4f(color[0], color[1], color[2], required ? 1.0f : 0.72f);
    GPU_line_width(required ? 3.0f : 2.2f);
    imm_draw_circle_wire_2d(pos, x, y, MOODBOARD_GRAPH_SOCKET_RADIUS - 1.5f, 24);
    GPU_line_width(1.0f);
  }
  immUnbindProgram();
}

void moodboard_draw_output_handle(const float x, const float y, const float color[3])
{
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(
      format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4f(0.05f, 0.05f, 0.06f, 0.95f);
  imm_draw_circle_fill_2d(pos, x, y, MOODBOARD_GRAPH_OUTPUT_RADIUS + 2.5f, 28);
  immUniformColor4f(color[0], color[1], color[2], 1.0f);
  imm_draw_circle_fill_2d(pos, x, y, MOODBOARD_GRAPH_OUTPUT_RADIUS, 28);
  immUniformColor4f(0.04f, 0.05f, 0.06f, 1.0f);
  GPU_line_width(2.5f);
  immBegin(GPU_PRIM_LINES, 4);
  immVertex2f(pos, x - 8.0f, y);
  immVertex2f(pos, x + 8.0f, y);
  immVertex2f(pos, x, y - 8.0f);
  immVertex2f(pos, x, y + 8.0f);
  immEnd();
  GPU_line_width(1.0f);
  immUnbindProgram();
}

/** Right-aligned socket name beside a selected node's input, so what each
 * socket accepts is readable before a noodle is committed to it. */
void moodboard_draw_socket_label(PointerRNA *socket,
                                 const float socket_x,
                                 const float socket_y)
{
  char label[MIXIE_GRAPH_LABEL_BUF];
  mixie_rna_string_get_clamped(socket, "label", label, sizeof(label));
  if (!label[0]) {
    return;
  }
  const int font_id = BLF_default();
  BLF_size(font_id, 13.0f);
  const float width = BLF_width(font_id, label, strlen(label));
  BLF_color4f(font_id, 0.86f, 0.87f, 0.90f, 0.82f);
  BLF_position(font_id,
               socket_x - MOODBOARD_GRAPH_SOCKET_RADIUS - 10.0f - width,
               socket_y - 5.0f,
               0.0f);
  BLF_draw(font_id, label, strlen(label));
}

}  // namespace blender::ed::mixie
