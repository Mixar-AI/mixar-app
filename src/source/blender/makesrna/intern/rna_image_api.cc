/* SPDX-FileCopyrightText: 2009 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup RNA
 */

#include <cstdlib>
#include <cstring>
#include <ctime>
#include <fcntl.h>

#include "BLI_path_utils.hh"

#include "RNA_define.hh"
#include "RNA_enum_types.hh"

#include "BKE_packedFile.hh"

#include "rna_internal.hh" /* own include */

#ifdef RNA_RUNTIME

#  include "BLI_listbase.h"
#  include "BLI_math_base.h"
#  include "BLI_string.h"

#  include "BKE_context.hh"
#  include "BKE_image.hh"
#  include "BKE_image_format.hh"
#  include "BKE_image_save.hh"
#  include "BKE_library.hh"
#  include "BKE_main.hh"
#  include "BKE_report.hh"
#  include "BKE_scene.hh"

#  include "IMB_imbuf.hh"

#  include "DNA_image_types.h"
#  include "DNA_scene_types.h"

/* Mixar: in-place movie frame upload (rna_Image_mixar_movie_frame_update). */
#  include "GPU_texture.hh"

#  include "MEM_guardedalloc.h"

#  include "WM_api.hh"

namespace blender {

static void rna_ImagePackedFile_save(ImagePackedFile *imapf, Main *bmain, ReportList *reports)
{
  if (BKE_packedfile_write_to_file(
          reports, BKE_main_blendfile_path(bmain), imapf->filepath, imapf->packedfile) != RET_OK)
  {
    BKE_reportf(reports, RPT_ERROR, "Could not save packed file to disk as '%s'", imapf->filepath);
  }
}

static void rna_Image_save_render(Image *image,
                                  bContext *C,
                                  ReportList *reports,
                                  const char *path,
                                  Scene *scene,
                                  const int quality)
{
  Main *bmain = CTX_data_main(C);

  if (scene == nullptr) {
    scene = CTX_data_scene(C);
  }

  ImageSaveOptions opts;

  if (BKE_image_save_options_init(&opts, bmain, scene, image, nullptr, false, true)) {
    opts.save_copy = true;
    STRNCPY(opts.filepath, path);
    if (quality != 0) {
      opts.im_format.quality = clamp_i(quality, 0, 100);
    }

    if (!BKE_image_save(reports, bmain, image, nullptr, &opts)) {
      BKE_reportf(
          reports, RPT_ERROR, "Image '%s' could not be saved to '%s'", image->id.name + 2, path);
    }
  }
  else {
    BKE_reportf(reports, RPT_ERROR, "Image '%s' does not have any image data", image->id.name + 2);
  }

  BKE_image_save_options_free(&opts);

  WM_event_add_notifier(C, NC_IMAGE | NA_EDITED, image);
}

static void rna_Image_save(Image *image,
                           Main *bmain,
                           bContext *C,
                           ReportList *reports,
                           const char *path,
                           const int quality,
                           const bool save_copy)
{
  Scene *scene = CTX_data_scene(C);
  ImageSaveOptions opts;

  if (BKE_image_save_options_init(&opts, bmain, scene, image, nullptr, false, false)) {
    if (path && path[0]) {
      STRNCPY(opts.filepath, path);
    }
    if (quality != 0) {
      opts.im_format.quality = clamp_i(quality, 0, 100);
    }
    opts.save_copy = save_copy;
    if (!BKE_image_save(reports, bmain, image, nullptr, &opts)) {
      BKE_reportf(reports,
                  RPT_ERROR,
                  "Image '%s' could not be saved to '%s'",
                  image->id.name + 2,
                  image->filepath);
    }
  }
  else {
    BKE_reportf(reports, RPT_ERROR, "Image '%s' does not have any image data", image->id.name + 2);
  }

  BKE_image_save_options_free(&opts);

  WM_event_add_notifier(C, NC_IMAGE | NA_EDITED, image);
}

static void rna_Image_pack(
    Image *image, Main *bmain, bContext *C, ReportList *reports, const char *data, int data_len)
{
  BKE_image_packfile_ensure(bmain, image, reports, data, data_len);
  WM_event_add_notifier(C, NC_IMAGE | NA_EDITED, image);
}

static void rna_Image_unpack(Image *image, Main *bmain, ReportList *reports, int method)
{
  if (!BKE_image_has_packedfile(image)) {
    BKE_report(reports, RPT_ERROR, "Image not packed");
    return;
  }

  if (!ID_IS_EDITABLE(&image->id)) {
    BKE_report(reports, RPT_ERROR, "Image is not editable");
    return;
  }

  if (ELEM(image->source, IMA_SRC_MOVIE, IMA_SRC_SEQUENCE)) {
    BKE_report(reports, RPT_ERROR, "Unpacking movies or image sequences not supported");
    return;
  }

  /* reports its own error on failure */
  BKE_packedfile_unpack_image(bmain, reports, image, ePF_FileStatus(method));
}

static void rna_Image_reload(Image *image, Main *bmain)
{
  BKE_image_signal(bmain, image, nullptr, IMA_SIGNAL_RELOAD);
  WM_main_add_notifier(NC_IMAGE | NA_EDITED, image);
}

static void rna_Image_update(Image *image, ReportList *reports)
{
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, nullptr);

  if (ibuf == nullptr) {
    BKE_reportf(reports, RPT_ERROR, "Image '%s' does not have any image data", image->id.name + 2);
    return;
  }

  if (ibuf->byte_data()) {
    IMB_byte_from_float(ibuf);
  }

  ibuf->userflags |= IB_DISPLAY_BUFFER_INVALID;
  BKE_image_partial_update_mark_full_update(image);

  BKE_image_release_ibuf(image, ibuf, nullptr);
}

static void rna_Image_scale(
    Image *image, ReportList *reports, int width, int height, int frame, int tile_index)
{
  ImageUser iuser{};
  BKE_imageuser_default(&iuser);
  iuser.framenr = frame;
  if (image->source == IMA_SRC_TILED) {
    const ImageTile *tile = static_cast<ImageTile *>(BLI_findlink(&image->tiles, tile_index));
    if (tile != nullptr) {
      iuser.tile = tile->tile_number;
    }
  }

  if (!BKE_image_scale(image, width, height, &iuser)) {
    BKE_reportf(reports, RPT_ERROR, "Image '%s' failed to load image buffer", image->id.name + 2);
    return;
  }
  BKE_image_partial_update_mark_full_update(image);
  WM_main_add_notifier(NC_IMAGE | NA_EDITED, image);
}

static int rna_Image_gl_load(
    Image *image, ReportList *reports, int frame, int layer_index, int pass_index)
{
  ImageUser iuser;
  BKE_imageuser_default(&iuser);
  iuser.framenr = frame;
  iuser.layer = layer_index;
  iuser.pass = pass_index;
  if (image->rr != nullptr) {
    BKE_image_multilayer_index(image->rr, &iuser);
  }

  gpu::Texture *tex = BKE_image_get_gpu_texture(image, &iuser);

  if (tex == nullptr) {
    BKE_reportf(reports, RPT_ERROR, "Failed to load image texture '%s'", image->id.name + 2);
    /* TODO(fclem): this error code makes no sense for vulkan. */
    return 0x0502; /* GL_INVALID_OPERATION */
  }

  return 0; /* GL_NO_ERROR */
}

static int rna_Image_gl_touch(
    Image *image, ReportList *reports, int frame, int layer_index, int pass_index)
{
  int error = 0; /* GL_NO_ERROR */

  BKE_image_tag_time(image);

  if (image->runtime->gputexture[TEXTARGET_2D][0] == nullptr) {
    error = rna_Image_gl_load(image, reports, frame, layer_index, pass_index);
  }

  return error;
}

static void rna_Image_gl_free(Image *image)
{
  BKE_image_free_gputextures(image);

  /* Remove the no-collect flag, image is available for garbage collection again. */
  image->flag &= ~IMA_NOCOLLECT;
}

/* Mixar: decode movie frame `frame` (1-based, like `gl_load`) and upload it into the image's
 * cached GPU texture IN PLACE. Blender's own frame handling (`BKE_image_user_frame_calc`) marks a
 * full update whenever the frame changes, which frees and recreates the texture; a Python draw
 * handler playing a video at 24 fps would therefore churn one texture per frame, and on Metal
 * that stalls the command buffer. Here the texture that `gpu.texture.from_image()` hands out is
 * kept alive and only its content changes, replicating exactly the conversion that
 * `IMB_create_gpu_texture` applied when the texture was created (`IMB_update_gpu_texture_sub`
 * runs the same `imb_gpu_get_data` path: colorspace, premultiplied alpha, grayscale packing). */
static bool rna_Image_mixar_movie_frame_update(Image *image, ReportList *reports, int frame)
{
  if (image->source != IMA_SRC_MOVIE) {
    BKE_reportf(reports, RPT_ERROR, "Image '%s' is not a movie", image->id.name + 2);
    return false;
  }

  ImageUser iuser;
  BKE_imageuser_default(&iuser);
  iuser.framenr = frame;

  /* Decode (or fetch from the movie cache) before touching the GPU so a failed decode never
   * leaves the 1x1 error texture behind. */
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, &iuser, nullptr);
  if (ibuf == nullptr) {
    BKE_reportf(reports,
                RPT_ERROR,
                "Image '%s' failed to decode movie frame %d",
                image->id.name + 2,
                frame);
    return false;
  }

  /* Get the cached texture. This also consumes any pending partial-update changeset; when that
   * (or first use) makes Blender create the texture, it is built from `iuser`, i.e. already from
   * this frame, and no second upload is needed. */
  gpu::Texture *const tex_before = image->runtime->gputexture[TEXTARGET_2D][0];
  gpu::Texture *tex = BKE_image_get_gpu_texture(image, &iuser);
  if (tex == nullptr) {
    BKE_image_release_ibuf(image, ibuf, nullptr);
    BKE_reportf(reports, RPT_ERROR, "Failed to load image texture '%s'", image->id.name + 2);
    return false;
  }

  bool updated = false;
  if (tex != tex_before) {
    updated = true;
  }
  else {
    const bool use_high_bitdepth = (image->flag & IMA_HIGH_BITDEPTH) != 0;
    const bool same_size = (GPU_texture_width(tex) == ibuf->x) &&
                           (GPU_texture_height(tex) == ibuf->y);
    const bool same_format = (GPU_texture_format(tex) ==
                              IMB_gpu_get_texture_format(ibuf, use_high_bitdepth, true));

    if (same_size && same_format) {
      const bool store_premultiplied = BKE_image_has_gpu_texture_premultiplied_alpha(image, ibuf);
      IMB_update_gpu_texture_sub(tex,
                                 ibuf,
                                 0,
                                 0,
                                 0,
                                 ibuf->x,
                                 ibuf->y,
                                 use_high_bitdepth,
                                 true,
                                 store_premultiplied);
      GPU_texture_update_mipmap_chain(tex);
      image->runtime->gpuflag |= IMA_GPU_MIPMAP_COMPLETE;
      updated = true;
    }
    else {
      /* Size-limited or differently typed texture: fall back to Blender's recreate path.
       * Callers must re-fetch `gpu.texture.from_image()` afterwards. */
      BKE_image_free_gputextures(image);
      updated = BKE_image_get_gpu_texture(image, &iuser) != nullptr;
    }
  }

  BKE_image_release_ibuf(image, ibuf, nullptr);

  if (updated) {
    /* Keep Blender's frame bookkeeping in agreement so `BKE_image_user_frame_calc` for the same
     * frame does not mark a full update (which would free the texture). */
    image->runtime->gpuframenr = frame;
  }
  return updated;
}

static void rna_Image_filepath_from_user(Image *image, ImageUser *image_user, char *filepath)
{
  BKE_image_user_file_path(image_user, image, filepath);
}

static void rna_Image_buffers_free(Image *image)
{
  BKE_image_free_buffers_ex(image, true);
}

}  // namespace blender

#else

namespace blender {

void RNA_api_image_packed_file(StructRNA *srna)
{
  FunctionRNA *func;

  func = RNA_def_function(srna, "save", "rna_ImagePackedFile_save");
  RNA_def_function_ui_description(func, "Save the packed file to its filepath");
  RNA_def_function_flag(func, FUNC_USE_MAIN | FUNC_USE_REPORTS);
}

void RNA_api_image(StructRNA *srna)
{
  FunctionRNA *func;
  PropertyRNA *parm;

  func = RNA_def_function(srna, "save_render", "rna_Image_save_render");
  RNA_def_function_ui_description(func,
                                  "Save image to a specific path using a scenes render settings");
  RNA_def_function_flag(func, FUNC_USE_CONTEXT | FUNC_USE_REPORTS);
  parm = RNA_def_string_file_path(func, "filepath", nullptr, 0, "", "Output path");
  RNA_def_parameter_flags(parm, PropertyFlag(0), PARM_REQUIRED);
  RNA_def_pointer(func, "scene", "Scene", "", "Scene to take image parameters from");
  RNA_def_int(func,
              "quality",
              0,
              0,
              100,
              "Quality",
              "Quality for image formats that support lossy compression, uses default quality if "
              "not specified",
              0,
              100);

  func = RNA_def_function(srna, "save", "rna_Image_save");
  RNA_def_function_ui_description(func, "Save image");
  RNA_def_function_flag(func, FUNC_USE_MAIN | FUNC_USE_CONTEXT | FUNC_USE_REPORTS);
  RNA_def_string_file_path(func,
                           "filepath",
                           nullptr,
                           0,
                           "",
                           "Output path, uses image data-block filepath if not specified");
  RNA_def_int(func,
              "quality",
              0,
              0,
              100,
              "Quality",
              "Quality for image formats that support lossy compression, uses default quality if "
              "not specified",
              0,
              100);
  RNA_def_boolean(func,
                  "save_copy",
                  false,
                  "Save Copy",
                  "Save the image as a copy, without updating current image's filepath");

  func = RNA_def_function(srna, "pack", "rna_Image_pack");
  RNA_def_function_ui_description(func, "Pack an image as embedded data into the .blend file");
  RNA_def_function_flag(func, FUNC_USE_MAIN | FUNC_USE_CONTEXT | FUNC_USE_REPORTS);
  parm = RNA_def_property(func, "data", PROP_STRING, PROP_BYTESTRING);
  RNA_def_property_ui_text(parm, "data", "Raw data (bytes, exact content of the embedded file)");
  RNA_def_int(func,
              "data_len",
              0,
              0,
              INT_MAX,
              "data_len",
              "length of given data (mandatory if data is provided)",
              0,
              INT_MAX);

  func = RNA_def_function(srna, "unpack", "rna_Image_unpack");
  RNA_def_function_ui_description(func, "Save an image packed in the .blend file to disk");
  RNA_def_function_flag(func, FUNC_USE_MAIN | FUNC_USE_REPORTS);
  RNA_def_enum(
      func, "method", rna_enum_unpack_method_items, PF_USE_LOCAL, "method", "How to unpack");

  func = RNA_def_function(srna, "reload", "rna_Image_reload");
  RNA_def_function_flag(func, FUNC_USE_MAIN);
  RNA_def_function_ui_description(func, "Reload the image from its source path");

  func = RNA_def_function(srna, "update", "rna_Image_update");
  RNA_def_function_ui_description(func, "Update the display image from the floating-point buffer");
  RNA_def_function_flag(func, FUNC_USE_REPORTS);

  func = RNA_def_function(srna, "scale", "rna_Image_scale");
  RNA_def_function_ui_description(func, "Scale the buffer of the image, in pixels");
  RNA_def_function_flag(func, FUNC_USE_REPORTS);
  parm = RNA_def_int(func, "width", 1, 1, INT_MAX, "", "Width", 1, INT_MAX);
  RNA_def_parameter_flags(parm, PropertyFlag(0), PARM_REQUIRED);
  parm = RNA_def_int(func, "height", 1, 1, INT_MAX, "", "Height", 1, INT_MAX);
  RNA_def_parameter_flags(parm, PropertyFlag(0), PARM_REQUIRED);
  RNA_def_int(func, "frame", 0, 0, INT_MAX, "Frame", "Frame (for image sequences)", 0, INT_MAX);
  RNA_def_int(
      func, "tile_index", 0, 0, INT_MAX, "Tile", "Tile index (for tiled images)", 0, INT_MAX);

  func = RNA_def_function(srna, "gl_touch", "rna_Image_gl_touch");
  RNA_def_function_ui_description(
      func, "Delay the image from being cleaned from the cache due inactivity");
  RNA_def_function_flag(func, FUNC_USE_REPORTS);
  RNA_def_int(
      func, "frame", 0, 0, INT_MAX, "Frame", "Frame of image sequence or movie", 0, INT_MAX);
  RNA_def_int(func,
              "layer_index",
              0,
              0,
              INT_MAX,
              "Layer",
              "Index of layer that should be loaded",
              0,
              INT_MAX);
  RNA_def_int(func,
              "pass_index",
              0,
              0,
              INT_MAX,
              "Pass",
              "Index of pass that should be loaded",
              0,
              INT_MAX);
  /* return value */
  parm = RNA_def_int(
      func, "error", 0, INT_MIN, INT_MAX, "Error", "OpenGL error value", INT_MIN, INT_MAX);
  RNA_def_function_return(func, parm);

  func = RNA_def_function(srna, "gl_load", "rna_Image_gl_load");
  RNA_def_function_ui_description(
      func,
      "Load the image into an OpenGL texture. On success, image.bindcode will contain the "
      "OpenGL texture bindcode. Colors read from the texture will be in scene linear color space "
      "and have premultiplied or straight alpha matching the image alpha mode.");
  RNA_def_function_flag(func, FUNC_USE_REPORTS);
  RNA_def_int(
      func, "frame", 0, 0, INT_MAX, "Frame", "Frame of image sequence or movie", 0, INT_MAX);
  RNA_def_int(func,
              "layer_index",
              0,
              0,
              INT_MAX,
              "Layer",
              "Index of layer that should be loaded",
              0,
              INT_MAX);
  RNA_def_int(func,
              "pass_index",
              0,
              0,
              INT_MAX,
              "Pass",
              "Index of pass that should be loaded",
              0,
              INT_MAX);
  /* return value */
  parm = RNA_def_int(
      func, "error", 0, INT_MIN, INT_MAX, "Error", "OpenGL error value", INT_MIN, INT_MAX);
  RNA_def_function_return(func, parm);

  func = RNA_def_function(srna, "gl_free", "rna_Image_gl_free");
  RNA_def_function_ui_description(func, "Free the image from OpenGL graphics memory");

  /* Mixar: in-place movie frame upload into the cached GPU texture. */
  func = RNA_def_function(srna, "mixar_movie_frame_update", "rna_Image_mixar_movie_frame_update");
  RNA_def_function_ui_description(
      func,
      "Decode a movie frame and upload it into the image's cached GPU texture in place, so "
      "gpu.texture.from_image() keeps returning the same texture (Mixar)");
  RNA_def_function_flag(func, FUNC_USE_REPORTS);
  parm = RNA_def_int(func, "frame", 1, 1, INT_MAX, "Frame", "Movie frame (1-based)", 1, INT_MAX);
  RNA_def_parameter_flags(parm, PropertyFlag(0), PARM_REQUIRED);
  /* return value */
  parm = RNA_def_boolean(
      func, "updated", false, "Updated", "True when the cached texture now holds the frame");
  RNA_def_function_return(func, parm);

  /* path to an frame specified by image user */
  func = RNA_def_function(srna, "filepath_from_user", "rna_Image_filepath_from_user");
  RNA_def_function_ui_description(
      func,
      "Return the absolute path to the filepath of an image frame specified by the image user");
  RNA_def_pointer(
      func, "image_user", "ImageUser", "", "Image user of the image to get filepath for");
  parm = RNA_def_string_file_path(func,
                                  "filepath",
                                  nullptr,
                                  FILE_MAX,
                                  "File Path",
                                  "The resulting filepath from the image and its user");
  RNA_def_parameter_flags(
      parm, PROP_THICK_WRAP, ParameterFlag(0)); /* needed for string return value */
  RNA_def_function_output(func, parm);

  func = RNA_def_function(srna, "buffers_free", "rna_Image_buffers_free");
  RNA_def_function_ui_description(func, "Free the image buffers from memory");

  /* TODO: pack/unpack, maybe should be generic functions? */
}

}  // namespace blender

#endif
