/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup shdnodes
 *
 * Mixar: X-Rite AxF SVBRDF BSDF (Lambert + Ward or GGX, per texel).
 *
 * Cycles evaluates the measured material exactly (intern/cycles/kernel/closure/
 * bsdf_axf_svbrdf.h) from the data atlas the Mixar AxF importer attaches to the node as
 * the ID property "axf_atlas". EEVEE renders a preview from the "Preview *" inputs, which
 * the importer links to preview textures of the same maps.
 *
 * Artist controls (Diffuse Tint, Specular Tint, Roughness, Normal Strength) default to
 * the measurement exactly; moving one is a deliberate edit of the look. The measured data
 * itself is never changed, so export still writes the original file. */

#include "node_shader_util.hh"

namespace blender {

namespace nodes::node_shader_bsdf_axf_svbrdf_cc {

static void node_declare(NodeDeclarationBuilder &b)
{
  const bNodeTree *ntree = b.tree_or_null();
  const bool is_gpu_internal = ntree && (ntree->flag & NTREE_IS_GPU_SHADER_INTERNAL);

  b.add_input<decl::Vector>("UV"_ustr)
      .hide_value()
      .description("Material map coordinates in map tile units");
  b.add_input<decl::Vector>("Normal"_ustr).hide_value();
  b.add_input<decl::Vector>("Tangent"_ustr)
      .hide_value()
      .description("Direction of increasing UV x, for the normal map and anisotropy");
  b.add_input<decl::Color>("Diffuse Tint"_ustr)
      .default_value({1.0f, 1.0f, 1.0f, 1.0f})
      .description("Multiplies the measured diffuse colour (white = as measured)");
  b.add_input<decl::Color>("Specular Tint"_ustr)
      .default_value({1.0f, 1.0f, 1.0f, 1.0f})
      .description("Multiplies the measured specular colour (white = as measured)");
  b.add_input<decl::Float>("Roughness"_ustr)
      .default_value(1.0f)
      .min(0.05f)
      .max(4.0f)
      .description("Scales the measured highlight width (1 = as measured)");
  b.add_input<decl::Float>("Normal Strength"_ustr)
      .default_value(1.0f)
      .min(0.0f)
      .max(4.0f)
      .description("Scales the measured normal map's relief (1 = as measured, 0 = flat)");
  b.add_input<decl::Color>("Preview Diffuse"_ustr)
      .default_value({0.5f, 0.5f, 0.5f, 1.0f})
      .description("EEVEE preview only: diffuse albedo");
  b.add_input<decl::Color>("Preview Specular"_ustr)
      .default_value({0.04f, 0.04f, 0.04f, 1.0f})
      .description("EEVEE preview only: specular albedo");
  b.add_input<decl::Float>("Preview Roughness"_ustr)
      .default_value(0.35f)
      .min(0.0f)
      .max(1.0f)
      .subtype(PROP_FACTOR)
      .description("EEVEE preview only: specular roughness");
  b.add_input<decl::Float>("Weight"_ustr).available(is_gpu_internal);
  b.add_output<decl::Shader>("BSDF"_ustr);
}

static int node_shader_gpu_bsdf_axf_svbrdf(GPUMaterial *mat,
                                           bNode *node,
                                           bNodeExecData * /*execdata*/,
                                           GPUNodeStack *in,
                                           GPUNodeStack *out)
{
  if (!in[1].link) {
    GPU_link(mat, "world_normals_get", &in[1].link);
  }
  GPU_material_flag_set(mat,
                        GPU_MATFLAG_DIFFUSE | GPU_MATFLAG_GLOSSY |
                            GPU_MATFLAG_REFLECTION_MAYBE_COLORED);
  return GPU_stack_link(mat, node, "node_bsdf_axf_svbrdf", in, out);
}

}  // namespace nodes::node_shader_bsdf_axf_svbrdf_cc

/* node type definition */
void register_node_type_sh_bsdf_axf_svbrdf()
{
  namespace file_ns = nodes::node_shader_bsdf_axf_svbrdf_cc;

  static bke::bNodeType ntype;

  sh_node_type_base(&ntype, "ShaderNodeBsdfAxFSvbrdf"_ustr, SH_NODE_BSDF_AXF_SVBRDF);
  ntype.ui_name = "AxF SVBRDF";
  ntype.ui_description =
      "Measured X-Rite AxF material (SVBRDF: Ward or GGX per texel): exact in Cycles, "
      "previewed in EEVEE";
  ntype.enum_name_legacy = "BSDF_AXF_SVBRDF";
  ntype.nclass = NODE_CLASS_SHADER;
  ntype.add_ui_poll = object_shader_nodes_poll;
  ntype.declare = file_ns::node_declare;
  ntype.gather_link_search_ops = search_link_ops_for_shader_bsdf_node;
  ntype.default_width = bke::NodeWidth::_240;
  ntype.gpu_fn = file_ns::node_shader_gpu_bsdf_axf_svbrdf;

  bke::node_register_type(ntype);
}

}  // namespace blender
