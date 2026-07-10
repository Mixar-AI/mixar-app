"""
Advanced texture handlers for Blender MCP Bridge.
Provides: texture/create-image, texture/open-image, texture/bake,
          texture/bake-from-highpoly, texture/paint-solid, texture/save,
          texture/pack, texture/channel-pack, texture/resize,
          texture/roughness-to-smoothness, texture/colorspace-validate,
          texture/list
"""

import os
from array import array
import bpy
from ...utils.response import ok_response, error_response, not_found, validate_filepath
from ...utils.context_helpers import ensure_context_for_object, temp_override
from .. import register_handler


def _get_pixels_array(img):
    """Read image pixels into a compact float array (much lighter than list())."""
    pixel_count = img.size[0] * img.size[1] * 4
    buf = array('f', [0.0]) * pixel_count
    img.pixels.foreach_get(buf)
    return buf


def _set_pixels_array(img, buf):
    """Write a float array back to image pixels."""
    img.pixels.foreach_set(buf)
    img.update()


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _get_image(name):
    """Return (image, None) or (None, error_response)."""
    img = bpy.data.images.get(name)
    if img is None:
        return None, not_found(name, "Image")
    return img, None


def _get_mesh_object(name):
    """Return (obj, None) or (None, error_response) for a MESH object."""
    obj = bpy.data.objects.get(name)
    if obj is None:
        return None, not_found(name, "Mesh object")
    if obj.type != "MESH":
        return None, error_response(
            f"Object '{name}' is of type '{obj.type}', not 'MESH'."
        )
    return obj, None


def _parse_channel_source(source_str):
    """
    Parse 'image_name:CHANNEL' into (image_name, channel_index).
    Channel: R=0, G=1, B=2, A=3.
    """
    channel_map = {"R": 0, "G": 1, "B": 2, "A": 3}
    if ":" not in source_str:
        return source_str, 0  # default to R channel
    parts = source_str.rsplit(":", 1)
    img_name = parts[0]
    ch = parts[1].upper() if len(parts) > 1 else "R"
    return img_name, channel_map.get(ch, 0)


def _ensure_object_has_bake_node(obj, image):
    """
    Ensure the object's active material has an Image Texture node set to
    the given image and that node is selected/active for baking.
    Creates a material if none exists.
    Returns the material used.
    """
    if not obj.data.materials:
        mat = bpy.data.materials.new(name=f"{obj.name}_BakeMat")
        mat.use_nodes = True
        obj.data.materials.append(mat)
    else:
        mat = obj.data.materials[0]
        if mat is None:
            mat = bpy.data.materials.new(name=f"{obj.name}_BakeMat")
            mat.use_nodes = True
            obj.data.materials[0] = mat

    if not mat.use_nodes:
        mat.use_nodes = True

    nodes = mat.node_tree.nodes

    # Find or create an Image Texture node designated for baking
    bake_node = None
    for node in nodes:
        if node.type == "TEX_IMAGE" and node.label == "__bake_target__":
            bake_node = node
            break

    if bake_node is None:
        bake_node = nodes.new(type="ShaderNodeTexImage")
        bake_node.label = "__bake_target__"

    bake_node.image = image

    # Deselect all nodes, then select the bake target and make it active
    for node in nodes:
        node.select = False
    bake_node.select = True
    nodes.active = bake_node

    return mat


# ─── Handlers ──────────────────────────────────────────────────────────────────

def _handle_create_image(params):
    """
    Create a new blank image data-block.
    Route: POST /api/texture/create-image
    """
    try:
        name = params.get("name")
        width = params.get("width")
        height = params.get("height")

        if not name:
            return error_response("Parameter 'name' is required.")
        if not width or not height:
            return error_response("Parameters 'width' and 'height' are required.")

        alpha = params.get("alpha", True)
        float_buffer = params.get("float", False)
        color = params.get("color", None)

        img = bpy.data.images.new(
            name,
            width=int(width),
            height=int(height),
            alpha=alpha,
            float_buffer=float_buffer,
        )

        if color is not None and len(color) == 4:
            pixel_count = width * height
            flat_color = list(color) * pixel_count
            img.pixels[:] = flat_color

        return ok_response({
            "image_name": img.name,
            "width": img.size[0],
            "height": img.size[1],
            "alpha": alpha,
            "float_buffer": float_buffer,
        })
    except Exception as e:
        return error_response(f"Failed to create image: {e}")


def _handle_open_image(params):
    """
    Load an image from disk.
    Route: POST /api/texture/open-image
    """
    try:
        filepath = params.get("filepath")
        if not filepath:
            return error_response("Parameter 'filepath' is required.")

        filepath, path_err = validate_filepath(filepath, must_exist=True)
        if path_err:
            return error_response(path_err)

        img = bpy.data.images.load(filepath)

        name = params.get("name")
        if name:
            img.name = name

        return ok_response({
            "image_name": img.name,
            "filepath": img.filepath,
            "width": img.size[0],
            "height": img.size[1],
            "colorspace": img.colorspace_settings.name,
        })
    except Exception as e:
        return error_response(f"Failed to open image '{params.get('filepath')}': {e}")


def _handle_bake(params):
    """
    Bake a texture map from the active object using Cycles.
    Route: POST /api/texture/bake
    """
    try:
        bake_type = params.get("type", "").upper()
        object_name = params.get("object_name")
        resolution = int(params.get("resolution", 1024))
        margin = int(params.get("margin", 16))

        if not bake_type:
            return error_response("Parameter 'type' is required.")
        if not object_name:
            return error_response("Parameter 'object_name' is required.")

        valid_types = ("DIFFUSE", "NORMAL", "ROUGHNESS", "AO", "EMIT", "COMBINED")
        if bake_type not in valid_types:
            return error_response(
                f"Unknown bake type '{bake_type}'. Valid: {', '.join(valid_types)}."
            )

        obj, err = _get_mesh_object(object_name)
        if err:
            return err

        # Ensure UV map exists
        if not obj.data.uv_layers:
            return error_response(
                f"Object '{object_name}' has no UV map. Add a UV map before baking."
            )

        # Switch to Cycles
        bpy.context.scene.render.engine = "CYCLES"

        # Create bake target image
        image_name = f"{object_name}_{bake_type.lower()}_bake"
        # Remove old bake image if it exists
        old = bpy.data.images.get(image_name)
        if old:
            bpy.data.images.remove(old)

        bake_img = bpy.data.images.new(image_name, resolution, resolution)

        # Set up bake node in material
        _ensure_object_has_bake_node(obj, bake_img)

        # Select and activate the object
        ensure_context_for_object(obj)

        with temp_override("VIEW_3D"):
            bpy.ops.object.bake(type=bake_type, margin=margin)

        return ok_response({
            "image_name": bake_img.name,
            "bake_type": bake_type,
            "object_name": obj.name,
            "resolution": resolution,
            "margin": margin,
        })
    except Exception as e:
        return error_response(f"Bake failed (type={params.get('type')}): {e}")


def _handle_bake_from_highpoly(params):
    """
    Bake from a high-poly mesh onto a low-poly mesh (Selected to Active).
    Route: POST /api/texture/bake-from-highpoly
    """
    try:
        highpoly_name = params.get("highpoly_name")
        lowpoly_name = params.get("lowpoly_name")
        bake_type = params.get("type", "").upper()
        cage_extrusion = float(params.get("cage_extrusion", 0.1))
        resolution = int(params.get("resolution", 1024))

        if not highpoly_name:
            return error_response("Parameter 'highpoly_name' is required.")
        if not lowpoly_name:
            return error_response("Parameter 'lowpoly_name' is required.")
        if not bake_type:
            return error_response("Parameter 'type' is required.")

        valid_types = ("DIFFUSE", "NORMAL", "ROUGHNESS", "AO", "EMIT", "COMBINED")
        if bake_type not in valid_types:
            return error_response(
                f"Unknown bake type '{bake_type}'. Valid: {', '.join(valid_types)}."
            )

        highpoly, err = _get_mesh_object(highpoly_name)
        if err:
            return err
        lowpoly, err = _get_mesh_object(lowpoly_name)
        if err:
            return err

        if not lowpoly.data.uv_layers:
            return error_response(
                f"Low-poly object '{lowpoly_name}' has no UV map. Add a UV map before baking."
            )

        # Switch to Cycles
        bpy.context.scene.render.engine = "CYCLES"

        # Create bake target image
        image_name = f"{lowpoly_name}_{bake_type.lower()}_from_{highpoly_name}"
        old = bpy.data.images.get(image_name)
        if old:
            bpy.data.images.remove(old)

        bake_img = bpy.data.images.new(image_name, resolution, resolution)

        # Set up bake node on the low-poly (the receiver)
        _ensure_object_has_bake_node(lowpoly, bake_img)

        # Deselect all, select high-poly, select low-poly, set low-poly active
        for o in bpy.context.scene.objects:
            o.select_set(False)
        highpoly.select_set(True)
        lowpoly.select_set(True)
        bpy.context.view_layer.objects.active = lowpoly

        with temp_override("VIEW_3D"):
            bpy.ops.object.bake(
                type=bake_type,
                use_selected_to_active=True,
                cage_extrusion=cage_extrusion,
            )

        return ok_response({
            "image_name": bake_img.name,
            "bake_type": bake_type,
            "highpoly": highpoly_name,
            "lowpoly": lowpoly_name,
            "cage_extrusion": cage_extrusion,
            "resolution": resolution,
        })
    except Exception as e:
        return error_response(f"High-poly bake failed: {e}")


def _handle_paint_solid(params):
    """
    Fill an image (or face region) with a solid RGBA color.
    Route: POST /api/texture/paint-solid
    """
    try:
        object_name = params.get("object_name")
        image_name = params.get("image_name")
        color = params.get("color")
        faces = params.get("faces", None)

        if not image_name:
            return error_response("Parameter 'image_name' is required.")
        if not color or len(color) != 4:
            return error_response("Parameter 'color' must be an RGBA list of 4 values.")

        img, err = _get_image(image_name)
        if err:
            return err

        width = img.size[0]
        height = img.size[1]
        total_pixels = width * height

        if faces is None:
            # Fill entire image
            img.pixels[:] = list(color) * total_pixels
            pixels_modified = total_pixels
        else:
            # Face-specific UV painting
            obj, err = _get_mesh_object(object_name)
            if err:
                return err

            if not obj.data.uv_layers:
                return error_response(
                    f"Object '{object_name}' has no UV map for face painting."
                )

            pixels = _get_pixels_array(img)  # compact float array instead of list
            uv_layer = obj.data.uv_layers.active.data
            mesh = obj.data
            pixels_modified = 0

            face_set = set(faces)
            for poly in mesh.polygons:
                if poly.index in face_set:
                    for loop_idx in poly.loop_indices:
                        uv = uv_layer[loop_idx].uv
                        px = int(uv.x * (width - 1)) % width
                        py = int(uv.y * (height - 1)) % height
                        flat_idx = (py * width + px) * 4
                        pixels[flat_idx]     = color[0]
                        pixels[flat_idx + 1] = color[1]
                        pixels[flat_idx + 2] = color[2]
                        pixels[flat_idx + 3] = color[3]
                        pixels_modified += 1

            _set_pixels_array(img, pixels)

        img.update()

        return ok_response({
            "image_name": img.name,
            "pixels_modified": pixels_modified,
            "color": color,
        })
    except Exception as e:
        return error_response(f"Paint solid failed: {e}")


def _handle_save(params):
    """
    Save an image data-block to disk.
    Route: POST /api/texture/save
    """
    try:
        image_name = params.get("image_name")
        filepath = params.get("filepath")
        fmt = params.get("format", "PNG").upper()

        if not image_name:
            return error_response("Parameter 'image_name' is required.")

        img, err = _get_image(image_name)
        if err:
            return err

        img.file_format = fmt

        if filepath:
            filepath, path_err = validate_filepath(filepath)
            if path_err:
                return error_response(path_err)
            img.filepath_raw = filepath
            img.save_render(filepath)
            saved_path = filepath
        else:
            if not img.filepath_raw and not img.filepath:
                return error_response(
                    f"Image '{image_name}' has no filepath. Provide 'filepath' parameter."
                )
            img.save()
            saved_path = img.filepath_raw or img.filepath

        file_size = None
        try:
            abs_path = bpy.path.abspath(saved_path)
            if os.path.isfile(abs_path):
                file_size = os.path.getsize(abs_path)
        except Exception:
            pass

        return ok_response({
            "image_name": img.name,
            "filepath": saved_path,
            "format": fmt,
            "file_size_bytes": file_size,
        })
    except Exception as e:
        return error_response(f"Save image failed: {e}")


def _handle_pack(params):
    """
    Pack one or all images into the .blend file.
    Route: POST /api/texture/pack
    """
    try:
        image_name = params.get("image_name")
        packed = []

        if image_name:
            img, err = _get_image(image_name)
            if err:
                return err
            img.pack()
            packed.append(img.name)
        else:
            for img in bpy.data.images:
                try:
                    img.pack()
                    packed.append(img.name)
                except Exception:
                    pass  # skip render results and other non-packable images

        return ok_response({
            "packed_images": packed,
            "count": len(packed),
        })
    except Exception as e:
        return error_response(f"Pack failed: {e}")


def _handle_channel_pack(params):
    """
    Create a new image by combining channels from source images.
    Route: POST /api/texture/channel-pack
    """
    try:
        output_name = params.get("output_name")
        r_source = params.get("r_source")
        g_source = params.get("g_source")
        b_source = params.get("b_source")
        a_source = params.get("a_source")

        if not output_name:
            return error_response("Parameter 'output_name' is required.")
        if not r_source or not g_source or not b_source:
            return error_response("Parameters 'r_source', 'g_source', 'b_source' are required.")

        sources = {
            "r": _parse_channel_source(r_source),
            "g": _parse_channel_source(g_source),
            "b": _parse_channel_source(b_source),
        }
        if a_source:
            sources["a"] = _parse_channel_source(a_source)

        # Load all referenced images and their pixel arrays
        img_pixels = {}
        img_size = None

        for ch, (img_name, _ch_idx) in sources.items():
            if img_name not in img_pixels:
                img, err = _get_image(img_name)
                if err:
                    return err
                if img_size is None:
                    img_size = (img.size[0], img.size[1])
                img_pixels[img_name] = _get_pixels_array(img)

        if img_size is None:
            return error_response("Could not determine image size from sources.")

        width, height = img_size
        total_pixels = width * height

        # Build output pixel array (RGBA) using compact array
        out_pixels = array('f', [0.0]) * (total_pixels * 4)

        def _sample(img_name, ch_idx, pixel_index):
            flat_idx = pixel_index * 4 + ch_idx
            pxls = img_pixels.get(img_name)
            if pxls and flat_idx < len(pxls):
                return pxls[flat_idx]
            return 0.0

        r_img, r_ch = sources["r"]
        g_img, g_ch = sources["g"]
        b_img, b_ch = sources["b"]

        for i in range(total_pixels):
            out_pixels[i * 4]     = _sample(r_img, r_ch, i)
            out_pixels[i * 4 + 1] = _sample(g_img, g_ch, i)
            out_pixels[i * 4 + 2] = _sample(b_img, b_ch, i)
            if "a" in sources:
                a_img, a_ch = sources["a"]
                out_pixels[i * 4 + 3] = _sample(a_img, a_ch, i)
            else:
                out_pixels[i * 4 + 3] = 1.0

        # Remove existing output image if present
        existing = bpy.data.images.get(output_name)
        if existing:
            bpy.data.images.remove(existing)

        out_img = bpy.data.images.new(output_name, width=width, height=height, alpha=True)
        out_img.pixels[:] = out_pixels

        return ok_response({
            "image_name": out_img.name,
            "width": width,
            "height": height,
            "sources": {
                "R": r_source,
                "G": g_source,
                "B": b_source,
                "A": a_source,
            },
        })
    except Exception as e:
        return error_response(f"Channel pack failed: {e}")


def _handle_resize(params):
    """
    Resize an image data-block in-place.
    Route: POST /api/texture/resize
    """
    try:
        image_name = params.get("image_name")
        width = params.get("width")
        height = params.get("height")

        if not image_name:
            return error_response("Parameter 'image_name' is required.")
        if not width or not height:
            return error_response("Parameters 'width' and 'height' are required.")

        img, err = _get_image(image_name)
        if err:
            return err

        old_w, old_h = img.size[0], img.size[1]
        img.scale(int(width), int(height))

        return ok_response({
            "image_name": img.name,
            "old_size": [old_w, old_h],
            "new_size": [img.size[0], img.size[1]],
        })
    except Exception as e:
        return error_response(f"Resize failed: {e}")


def _handle_roughness_to_smoothness(params):
    """
    Invert a roughness map to produce a smoothness map (1.0 - value per RGB channel).
    Route: POST /api/texture/roughness-to-smoothness
    """
    try:
        image_name = params.get("image_name")
        output_name = params.get("output_name")

        if not image_name:
            return error_response("Parameter 'image_name' is required.")

        src_img, err = _get_image(image_name)
        if err:
            return err

        src_pixels = _get_pixels_array(src_img)
        total_pixels = src_img.size[0] * src_img.size[1]
        out_pixels = array('f', src_pixels)  # copy

        # Invert R, G, B channels; leave A unchanged
        for i in range(total_pixels):
            base = i * 4
            out_pixels[base]     = 1.0 - src_pixels[base]
            out_pixels[base + 1] = 1.0 - src_pixels[base + 1]
            out_pixels[base + 2] = 1.0 - src_pixels[base + 2]
            # out_pixels[base + 3] = src_pixels[base + 3]  # alpha unchanged (already copied)

        if output_name and output_name != image_name:
            existing = bpy.data.images.get(output_name)
            if existing:
                bpy.data.images.remove(existing)
            out_img = bpy.data.images.new(
                output_name,
                width=src_img.size[0],
                height=src_img.size[1],
                alpha=True,
            )
            out_img.pixels[:] = out_pixels
            result_name = out_img.name
        else:
            # Modify in-place
            src_img.pixels[:] = out_pixels
            result_name = src_img.name

        return ok_response({
            "image_name": result_name,
            "source_image": image_name,
            "operation": "roughness_to_smoothness",
        })
    except Exception as e:
        return error_response(f"Roughness to smoothness conversion failed: {e}")


def _handle_colorspace_validate(params):
    """
    Scan materials for Image Texture nodes with incorrect color-space settings.
    Route: POST /api/texture/colorspace-validate
    """
    try:
        object_name = params.get("object_name")

        # Determine which materials to scan
        if object_name:
            obj = bpy.data.objects.get(object_name)
            if obj is None:
                return not_found(object_name)
            materials = [
                slot.material for slot in obj.material_slots
                if slot.material is not None
            ]
        else:
            materials = list(bpy.data.materials)

        # Sockets that indicate non-color / data usage
        DATA_SOCKET_NAMES = {
            "Normal", "Roughness", "Metallic", "Subsurface",
            "Transmission", "IOR", "Specular", "Emission Strength",
            "Alpha", "Anisotropic", "Anisotropic Rotation",
            "Clearcoat", "Clearcoat Roughness", "Sheen", "Sheen Tint",
        }

        mismatches = []
        ok_count = 0

        for mat in materials:
            if not mat.use_nodes:
                continue
            nodes = mat.node_tree.nodes
            links = mat.node_tree.links

            for node in nodes:
                if node.type != "TEX_IMAGE":
                    continue
                if node.image is None:
                    continue

                current_cs = node.image.colorspace_settings.name
                image_name_str = node.image.name

                # Determine expected color space by inspecting downstream links
                expected_cs = None
                for link in links:
                    if link.from_node == node and link.from_socket.name == "Color":
                        to_socket = link.to_socket.name
                        if to_socket in DATA_SOCKET_NAMES:
                            expected_cs = "Non-Color"
                        elif to_socket == "Color":
                            expected_cs = "sRGB"
                        elif to_socket == "Normal":
                            expected_cs = "Non-Color"
                        else:
                            # Assume color data for Base Color and other color inputs
                            expected_cs = "sRGB"
                        break

                if expected_cs is None:
                    # Cannot determine — skip
                    ok_count += 1
                    continue

                if current_cs != expected_cs:
                    mismatches.append({
                        "material": mat.name,
                        "image": image_name_str,
                        "current_colorspace": current_cs,
                        "expected_colorspace": expected_cs,
                        "connected_to": link.to_socket.name if links else "unknown",
                    })
                else:
                    ok_count += 1

        return ok_response({
            "mismatches": mismatches,
            "mismatch_count": len(mismatches),
            "ok_count": ok_count,
            "materials_scanned": len(materials),
        })
    except Exception as e:
        return error_response(f"Colorspace validation failed: {e}")


def _handle_list(params):
    """
    List all image data-blocks in the current Blender session.
    Route: POST /api/texture/list
    """
    try:
        images = []
        for img in bpy.data.images:
            images.append({
                "name": img.name,
                "width": img.size[0],
                "height": img.size[1],
                "filepath": img.filepath,
                "colorspace": img.colorspace_settings.name,
                "is_dirty": img.is_dirty,
                "has_data": img.has_data,
                "packed": img.packed_file is not None,
                "file_format": img.file_format,
            })

        return ok_response({
            "images": images,
            "count": len(images),
        })
    except Exception as e:
        return error_response(f"Failed to list images: {e}")


# ─── Register routes ────────────────────────────────────────────────────────────

register_handler("texture", "create-image",             _handle_create_image)
register_handler("texture", "open-image",               _handle_open_image)
register_handler("texture", "bake",                     _handle_bake)
register_handler("texture", "bake-from-highpoly",       _handle_bake_from_highpoly)
register_handler("texture", "paint-solid",              _handle_paint_solid)
register_handler("texture", "save",                     _handle_save)
register_handler("texture", "pack",                     _handle_pack)
register_handler("texture", "channel-pack",             _handle_channel_pack)
register_handler("texture", "resize",                   _handle_resize)
register_handler("texture", "roughness-to-smoothness",  _handle_roughness_to_smoothness)
register_handler("texture", "colorspace-validate",      _handle_colorspace_validate)
register_handler("texture", "list",                     _handle_list)
