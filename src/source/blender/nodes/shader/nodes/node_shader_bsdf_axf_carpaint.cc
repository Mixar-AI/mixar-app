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
 * "Preview *" inputs, which the importer derives from the same data. */

#include "node_shader_util.hh"

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
  return GPU_stack_link(mat, node, "node_bsdf_axf_carpaint", in, out);
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
