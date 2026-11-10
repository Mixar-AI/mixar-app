/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup shdnodes
 *
 * Mixar: X-Rite AxF CarPaint2 BSDF.
 *
 * Cycles evaluates the measured material exactly (intern/cycles/kernel/closure/
 * bsdf_axf_carpaint.h) from images the Mixar AxF importer attaches to the node as ID
 * properties: "axf_table" (colour table + parameter stream), "axf_flakes" (flake BTF
 * atlas) and "axf_coat_normal" (clear coat normal map, when the file has one). EEVEE
 * cannot evaluate a per-light measured BRDF, so it renders a preview from the
 * "Preview *" inputs, which the importer derives from the same data.
 *
 * Artist controls (Tint, Flake Strength, Orange Peel, Coat Reflection, Coat Roughness)
 * default to the measurement exactly; moving one is a deliberate edit of the look. The
 * measured data itself is never changed, so export still writes the original file. */

#include "node_shader_util.hh"

#include "BKE_idprop.hh"

#include "DNA_image_types.h"

namespace blender {

namespace nodes::node_shader_bsdf_axf_carpaint_cc {

static void node_declare(NodeDeclarationBuilder &b)
{
  const bNodeTree *ntree = b.tree_or_null();
  const bool is_gpu_internal = ntree && (ntree->flag & NTREE_IS_GPU_SHADER_INTERNAL);

  b.add_input<decl::Vector>("Flake UV"_ustr)
      .hide_value()
      .description("Flake texture coordinates in AxF flake patch units");
  b.add_input<decl::Vector>("Coat UV"_ustr)
      .hide_value()
      .description("Clear coat normal map coordinates in map tile units");
  b.add_input<decl::Vector>("Normal"_ustr).hide_value();
  b.add_input<decl::Vector>("Tangent"_ustr)
      .hide_value()
      .description("Direction of increasing Coat UV x, for the clear coat normal map");
  b.add_input<decl::Color>("Tint"_ustr)
      .default_value({1.0f, 1.0f, 1.0f, 1.0f})
      .description("Multiplies the paint under the clear coat (white = as measured)");
  b.add_input<decl::Float>("Flake Strength"_ustr)
      .default_value(1.0f)
      .min(0.0f)
      .max(10.0f)
      .description("Scales the measured flake sparkle (1 = as measured)");
  b.add_input<decl::Float>("Orange Peel"_ustr)
      .default_value(1.0f)
      .min(0.0f)
      .max(10.0f)
      .description("Scales the clear coat normal map's waviness (1 = as measured, 0 = flat)");
  b.add_input<decl::Float>("Coat Reflection"_ustr)
      .default_value(1.0f)
      .min(0.0f)
      .max(2.0f)
      .subtype(PROP_FACTOR)
      .description("Scales the clear coat's mirror reflection (1 = as measured)");
  b.add_input<decl::Float>("Coat Roughness"_ustr)
      .default_value(0.0f)
      .min(0.0f)
      .max(1.0f)
      .subtype(PROP_FACTOR)
      .description("Blurs the clear coat reflection (0 = the measured mirror)");
  b.add_input<decl::Color>("Preview Diffuse"_ustr)
      .default_value({0.5f, 0.05f, 0.05f, 1.0f})
      .description("EEVEE preview only: diffuse albedo");
  b.add_input<decl::Color>("Preview Specular"_ustr)
      .default_value({0.2f, 0.02f, 0.02f, 1.0f})
      .description("EEVEE preview only: base specular albedo");
  b.add_input<decl::Float>("Preview Roughness"_ustr)
      .default_value(0.35f)
      .min(0.0f)
      .max(1.0f)
      .subtype(PROP_FACTOR)
      .description("EEVEE preview only: base specular roughness");
  b.add_input<decl::Float>("Coat IOR"_ustr)
      .default_value(1.5f)
      .min(1.0f)
      .max(4.0f)
      .description("EEVEE preview only: clear coat index of refraction");
  b.add_input<decl::Float>("Weight"_ustr).available(is_gpu_internal);
  b.add_output<decl::Shader>("BSDF"_ustr);
}

/* The data image an ID property of the node references (the importer's contract). */
static Image *node_image_prop(const bNode *node, const char *name)
{
  if (node->prop == nullptr) {
    return nullptr;
  }
  const IDProperty *prop = IDP_GetPropertyFromGroup(node->prop, name);
  if (prop == nullptr || prop->type != IDP_ID) {
    return nullptr;
  }
  ID *id = static_cast<ID *>(prop->data.pointer);
  if (id == nullptr || GS(id->name) != ID_IM) {
    return nullptr;
  }
  return reinterpret_cast<Image *>(id);
}

static int node_shader_gpu_bsdf_axf_carpaint(GPUMaterial *mat,
                                             bNode *node,
                                             bNodeExecData * /*execdata*/,
                                             GPUNodeStack *in,
                                             GPUNodeStack *out)
{
  if (!in[2].link) {
    GPU_link(mat, "world_normals_get", &in[2].link);
  }
  GPU_material_flag_set(mat,
                        GPU_MATFLAG_DIFFUSE | GPU_MATFLAG_GLOSSY | GPU_MATFLAG_COAT |
                            GPU_MATFLAG_REFLECTION_MAYBE_COLORED);

  /* Imports that carry the per-view fit ("axf_eevee_fit") follow the view angle and show
   * the measured flakes; older ones use the constant Preview inputs. */
  Image *fit = node_image_prop(node, "axf_eevee_fit");
  Image *table = node_image_prop(node, "axf_table");
  if (fit == nullptr || table == nullptr) {
    return GPU_stack_link(mat, node, "node_bsdf_axf_carpaint", in, out);
  }
  Image *flakes = node_image_prop(node, "axf_flakes");
  /* Light inside the material shader (EEVEE's forward / deferred hybrid pass), where the
   * node evaluates the measured BRDF per light. */
  GPU_material_flag_set(mat, GPU_MATFLAG_SHADER_TO_RGBA);

  GPUSamplerState linear = GPUSamplerState::default_sampler();
  linear.filtering = GPU_SAMPLER_FILTERING_LINEAR;
  linear.extend_x = GPU_SAMPLER_EXTEND_MODE_EXTEND;
  linear.extend_yz = GPU_SAMPLER_EXTEND_MODE_EXTEND;
  /* Data images are read with exact texel fetches. */
  GPUSamplerState texels = GPUSamplerState::default_sampler();
  texels.extend_x = GPU_SAMPLER_EXTEND_MODE_EXTEND;
  texels.extend_yz = GPU_SAMPLER_EXTEND_MODE_EXTEND;

  GPUNodeLink *fit_link = GPU_image(mat, fit, nullptr, linear);
  GPUNodeLink *table_link = GPU_image(mat, table, nullptr, texels);
  /* Without flakes the table stands in for the (unread) flakes sampler. It needs a link of
   * its own: GPU_stack_link frees every non-output link it consumes, so passing
   * table_link twice is a double free (crash on any paint without flakes). */
  GPUNodeLink *flakes_link = GPU_image(mat, flakes ? flakes : table, nullptr, texels);
  const float has_flakes = flakes ? 1.0f : 0.0f;
  return GPU_stack_link(mat,
                        node,
                        "node_bsdf_axf_carpaint_fit",
                        in,
                        out,
                        fit_link,
                        table_link,
                        flakes_link,
                        GPU_constant(&has_flakes));
}

}  // namespace nodes::node_shader_bsdf_axf_carpaint_cc

/* node type definition */
void register_node_type_sh_bsdf_axf_carpaint()
{
  namespace file_ns = nodes::node_shader_bsdf_axf_carpaint_cc;

  static bke::bNodeType ntype;

  sh_node_type_base(&ntype, "ShaderNodeBsdfAxFCarPaint"_ustr, SH_NODE_BSDF_AXF_CARPAINT);
  ntype.ui_name = "AxF Car Paint BSDF";
  ntype.ui_description =
      "Measured X-Rite AxF car paint (CarPaint2): exact in Cycles, previewed in EEVEE";
  ntype.enum_name_legacy = "BSDF_AXF_CARPAINT";
  ntype.nclass = NODE_CLASS_SHADER;
  ntype.add_ui_poll = object_shader_nodes_poll;
  ntype.declare = file_ns::node_declare;
  ntype.gather_link_search_ops = search_link_ops_for_shader_bsdf_node;
  ntype.default_width = bke::NodeWidth::_240;
  ntype.gpu_fn = file_ns::node_shader_gpu_bsdf_axf_carpaint;

  bke::node_register_type(ntype);
}

}  // namespace blender
