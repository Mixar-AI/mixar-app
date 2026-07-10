"""
Advanced light handlers for Blender MCP Bridge.
Provides: light/create, light/configure, light/sun-setup, light/three-point,
          light/hdri-setup, light/world-color, light/list, light/shadow-settings
"""

import math
import bpy
from ...utils.response import ok_response, error_response, not_found
from ...utils.context_helpers import ensure_context_for_object, temp_override
from .. import register_handler


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _get_light_object(name):
    """Return (obj, None) or (None, error_response) for a LIGHT object."""
    obj = bpy.data.objects.get(name)
    if obj is None:
        return None, not_found(name, "Light")
    if obj.type != "LIGHT":
        return None, error_response(
            f"Object '{name}' is of type '{obj.type}', not 'LIGHT'."
        )
    return obj, None


def _ensure_world():
    """Return the scene world, creating one if none exists."""
    world = bpy.context.scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        bpy.context.scene.world = world
    return world


def _ensure_world_nodes(world):
    """Enable nodes on the world and return the node tree."""
    world.use_nodes = True
    return world.node_tree


def _get_or_create_background_node(node_tree):
    """Return the Background node, creating it if needed."""
    for node in node_tree.nodes:
        if node.type == "BACKGROUND":
            return node
    bg = node_tree.nodes.new("ShaderNodeBackground")
    return bg


def _direction_to_rotation(position, target):
    """Compute Euler rotation so that -Z points from position toward target."""
    from mathutils import Vector
    pos = Vector(position)
    tgt = Vector(target)
    direction = tgt - pos
    if direction.length < 1e-6:
        from mathutils import Euler
        return Euler((0.0, 0.0, 0.0), "XYZ")
    rotation = direction.to_track_quat("-Z", "Y").to_euler()
    return rotation


# ─── Handlers ──────────────────────────────────────────────────────────────────

def _handle_light_create(params):
    """
    Create a new light object.
    Route: POST /api/light/create
    """
    try:
        light_type = params.get("type", "POINT").upper()
        name = params.get("name", "Light")
        location = params.get("location", [0.0, 0.0, 0.0])
        energy = params.get("energy", None)
        color = params.get("color", None)

        valid_types = ("POINT", "SUN", "SPOT", "AREA")
        if light_type not in valid_types:
            return error_response(
                f"Unknown light type '{light_type}'. Valid: {', '.join(valid_types)}."
            )

        light_data = bpy.data.lights.new(name=name, type=light_type)

        if energy is not None:
            light_data.energy = float(energy)
        if color is not None:
            light_data.color = (float(color[0]), float(color[1]), float(color[2]))

        obj = bpy.data.objects.new(name=name, object_data=light_data)
        bpy.context.collection.objects.link(obj)
        obj.location = (float(location[0]), float(location[1]), float(location[2]))

        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        return ok_response({
            "object_name": obj.name,
            "light_type": light_data.type,
            "energy": light_data.energy,
            "color": list(light_data.color),
            "location": [round(v, 6) for v in obj.location],
        })
    except Exception as e:
        return error_response(f"Failed to create light: {e}")


def _handle_light_configure(params):
    """
    Configure properties of an existing light.
    Route: POST /api/light/configure
    """
    name = params.get("name")
    if not name:
        return error_response("Parameter 'name' is required.")

    obj, err = _get_light_object(name)
    if err:
        return err

    try:
        light_data = obj.data
        applied = {}

        energy = params.get("energy")
        if energy is not None:
            light_data.energy = float(energy)
            applied["energy"] = light_data.energy

        color = params.get("color")
        if color is not None:
            light_data.color = (float(color[0]), float(color[1]), float(color[2]))
            applied["color"] = list(light_data.color)

        radius = params.get("radius")
        if radius is not None:
            light_data.shadow_soft_size = float(radius)
            applied["radius"] = light_data.shadow_soft_size

        angle = params.get("angle")
        if angle is not None:
            if light_data.type == "SPOT":
                light_data.spot_size = math.radians(float(angle))
                applied["angle_degrees"] = float(angle)
            else:
                applied["angle_skipped"] = f"angle only applies to SPOT, got {light_data.type}"

        shadow = params.get("shadow")
        if shadow is not None:
            light_data.use_shadow = bool(shadow)
            applied["use_shadow"] = light_data.use_shadow

        return ok_response({
            "object_name": obj.name,
            "light_type": light_data.type,
            "applied": applied,
        })
    except Exception as e:
        return error_response(f"Failed to configure light '{name}': {e}")


def _handle_light_sun_setup(params):
    """
    Create or reconfigure a SUN light.
    Route: POST /api/light/sun-setup
    """
    rotation = params.get("rotation")
    if rotation is None:
        return error_response("Parameter 'rotation' is required.")

    energy = params.get("energy", 5.0)
    color = params.get("color", [1.0, 1.0, 1.0])

    try:
        # Find existing SUN light or create one
        sun_obj = None
        for obj in bpy.data.objects:
            if obj.type == "LIGHT" and obj.data.type == "SUN":
                sun_obj = obj
                break

        if sun_obj is None:
            light_data = bpy.data.lights.new(name="Sun", type="SUN")
            sun_obj = bpy.data.objects.new(name="Sun", object_data=light_data)
            bpy.context.collection.objects.link(sun_obj)

        light_data = sun_obj.data
        light_data.energy = float(energy)
        light_data.color = (float(color[0]), float(color[1]), float(color[2]))

        # Apply rotation (degrees → radians)
        sun_obj.rotation_euler = (
            math.radians(float(rotation[0])),
            math.radians(float(rotation[1])),
            math.radians(float(rotation[2])),
        )

        bpy.context.view_layer.objects.active = sun_obj
        sun_obj.select_set(True)

        return ok_response({
            "object_name": sun_obj.name,
            "light_type": "SUN",
            "energy": light_data.energy,
            "color": list(light_data.color),
            "rotation_degrees": [round(math.degrees(v), 4) for v in sun_obj.rotation_euler],
        })
    except Exception as e:
        return error_response(f"Failed to set up sun light: {e}")


def _handle_light_three_point(params):
    """
    Create a classic three-point lighting rig.
    Route: POST /api/light/three-point
    """
    target = params.get("target", [0.0, 0.0, 0.0])
    key_energy = float(params.get("key_energy", 1000.0))
    fill_energy = float(params.get("fill_energy", 400.0))
    rim_energy = float(params.get("rim_energy", 600.0))

    try:
        # Define light positions relative to target
        tx, ty, tz = float(target[0]), float(target[1]), float(target[2])

        lights_spec = [
            {
                "name": "Key_Light",
                "position": [tx - 3.0, ty - 4.0, tz + 4.0],
                "energy": key_energy,
                "color": (1.0, 1.0, 1.0),
            },
            {
                "name": "Fill_Light",
                "position": [tx + 3.0, ty - 3.0, tz + 2.0],
                "energy": fill_energy,
                "color": (0.9, 0.95, 1.0),
            },
            {
                "name": "Rim_Light",
                "position": [tx + 1.0, ty + 5.0, tz + 3.0],
                "energy": rim_energy,
                "color": (1.0, 0.98, 0.95),
            },
        ]

        created = []
        for spec in lights_spec:
            # Remove existing light with this name if present
            existing = bpy.data.objects.get(spec["name"])
            if existing is not None and existing.type == "LIGHT":
                bpy.data.objects.remove(existing, do_unlink=True)

            light_data = bpy.data.lights.new(name=spec["name"], type="AREA")
            light_data.energy = spec["energy"]
            light_data.color = spec["color"]

            obj = bpy.data.objects.new(name=spec["name"], object_data=light_data)
            bpy.context.collection.objects.link(obj)
            obj.location = spec["position"]

            # Point light toward target
            rotation = _direction_to_rotation(spec["position"], [tx, ty, tz])
            obj.rotation_euler = rotation

            created.append({
                "object_name": obj.name,
                "role": spec["name"].split("_")[0].lower(),
                "location": [round(v, 4) for v in obj.location],
                "energy": light_data.energy,
            })

        return ok_response({
            "target": [tx, ty, tz],
            "lights": created,
        })
    except Exception as e:
        return error_response(f"Failed to create three-point lighting rig: {e}")


def _handle_light_hdri_setup(params):
    """
    Set up HDRI image-based environment lighting.
    Route: POST /api/light/hdri-setup
    """
    hdri_path = params.get("hdri_path")
    if not hdri_path:
        return error_response("Parameter 'hdri_path' is required.")

    rotation_deg = float(params.get("rotation", 0.0))
    strength = float(params.get("strength", 1.0))

    try:
        world = _ensure_world()
        nt = _ensure_world_nodes(world)

        # Clear existing nodes
        nt.nodes.clear()

        # Create required nodes
        node_output = nt.nodes.new("ShaderNodeOutputWorld")
        node_bg = nt.nodes.new("ShaderNodeBackground")
        node_env = nt.nodes.new("ShaderNodeTexEnvironment")
        node_mapping = nt.nodes.new("ShaderNodeMapping")
        node_texcoord = nt.nodes.new("ShaderNodeTexCoord")

        # Arrange nodes left to right
        node_texcoord.location = (-900, 300)
        node_mapping.location = (-600, 300)
        node_env.location = (-300, 300)
        node_bg.location = (0, 300)
        node_output.location = (300, 300)

        # Load HDRI image
        img = bpy.data.images.load(hdri_path, check_existing=True)
        node_env.image = img

        # Set strength
        node_bg.inputs["Strength"].default_value = strength

        # Set rotation on Mapping node (Z axis)
        node_mapping.inputs["Rotation"].default_value[2] = math.radians(rotation_deg)

        # Wire nodes: TexCoord.Generated → Mapping.Vector → EnvTex.Vector → Background.Color → Output.Surface
        nt.links.new(node_texcoord.outputs["Generated"], node_mapping.inputs["Vector"])
        nt.links.new(node_mapping.outputs["Vector"], node_env.inputs["Vector"])
        nt.links.new(node_env.outputs["Color"], node_bg.inputs["Color"])
        nt.links.new(node_bg.outputs["Background"], node_output.inputs["Surface"])

        return ok_response({
            "world_name": world.name,
            "hdri_path": hdri_path,
            "strength": strength,
            "rotation_degrees": rotation_deg,
            "image_name": img.name,
        })
    except Exception as e:
        return error_response(f"Failed to set up HDRI lighting: {e}")


def _handle_light_world_color(params):
    """
    Set the scene world background to a solid color.
    Route: POST /api/light/world-color
    """
    color = params.get("color")
    if color is None:
        return error_response("Parameter 'color' is required.")

    strength = float(params.get("strength", 1.0))

    try:
        world = _ensure_world()
        nt = _ensure_world_nodes(world)

        # Find or create Background and World Output nodes
        node_bg = None
        node_output = None
        for node in nt.nodes:
            if node.type == "BACKGROUND":
                node_bg = node
            elif node.type == "OUTPUT_WORLD":
                node_output = node

        if node_bg is None:
            node_bg = nt.nodes.new("ShaderNodeBackground")
            node_bg.location = (0, 300)

        if node_output is None:
            node_output = nt.nodes.new("ShaderNodeOutputWorld")
            node_output.location = (300, 300)

        # Set color (RGBA — alpha defaults to 1.0)
        node_bg.inputs["Color"].default_value = (
            float(color[0]),
            float(color[1]),
            float(color[2]),
            1.0,
        )
        node_bg.inputs["Strength"].default_value = strength

        # Ensure Background is connected to Output
        linked = any(
            link.from_node == node_bg and link.to_node == node_output
            for link in nt.links
        )
        if not linked:
            nt.links.new(node_bg.outputs["Background"], node_output.inputs["Surface"])

        return ok_response({
            "world_name": world.name,
            "color": [float(color[0]), float(color[1]), float(color[2])],
            "strength": strength,
        })
    except Exception as e:
        return error_response(f"Failed to set world color: {e}")


def _handle_light_list(params):
    """
    List all light objects in the scene.
    Route: POST /api/light/list
    """
    try:
        lights = []
        for obj in bpy.data.objects:
            if obj.type != "LIGHT":
                continue
            ld = obj.data
            entry = {
                "name": obj.name,
                "object_name": obj.name,
                "light_type": ld.type,
                "location": [round(v, 6) for v in obj.location],
                "energy": ld.energy,
                "color": [round(v, 6) for v in ld.color],
            }
            if ld.type == "SPOT":
                entry["spot_size_degrees"] = round(math.degrees(ld.spot_size), 4)
            lights.append(entry)

        return ok_response({
            "count": len(lights),
            "lights": lights,
        })
    except Exception as e:
        return error_response(f"Failed to list lights: {e}")


def _handle_light_shadow_settings(params):
    """
    Configure shadow properties on an existing light.
    Route: POST /api/light/shadow-settings
    """
    name = params.get("name")
    shadow_params = params.get("params") or {}

    if not name:
        return error_response("Parameter 'name' is required.")
    if not shadow_params:
        return error_response("Parameter 'params' must be a non-empty object.")

    obj, err = _get_light_object(name)
    if err:
        return err

    try:
        light_data = obj.data
        applied = {}

        use_shadow = shadow_params.get("use_shadow")
        if use_shadow is not None:
            light_data.use_shadow = bool(use_shadow)
            applied["use_shadow"] = light_data.use_shadow

        shadow_soft_size = shadow_params.get("shadow_soft_size")
        if shadow_soft_size is not None:
            light_data.shadow_soft_size = float(shadow_soft_size)
            applied["shadow_soft_size"] = light_data.shadow_soft_size

        clip_start = shadow_params.get("shadow_buffer_clip_start")
        if clip_start is not None:
            try:
                light_data.shadow_buffer_clip_start = float(clip_start)
                applied["shadow_buffer_clip_start"] = light_data.shadow_buffer_clip_start
            except AttributeError:
                applied["shadow_buffer_clip_start_skipped"] = "not available in this Blender version"

        cascade_count = shadow_params.get("shadow_cascade_count")
        if cascade_count is not None:
            if light_data.type == "SUN":
                try:
                    light_data.shadow_cascade_count = int(cascade_count)
                    applied["shadow_cascade_count"] = light_data.shadow_cascade_count
                except AttributeError:
                    applied["shadow_cascade_count_skipped"] = "not available in this Blender version"
            else:
                applied["shadow_cascade_count_skipped"] = f"only applies to SUN lights, got {light_data.type}"

        contact_distance = shadow_params.get("contact_shadow_distance")
        if contact_distance is not None:
            try:
                light_data.contact_shadow_distance = float(contact_distance)
                applied["contact_shadow_distance"] = light_data.contact_shadow_distance
            except AttributeError:
                applied["contact_shadow_distance_skipped"] = "not available in this Blender version"

        return ok_response({
            "object_name": obj.name,
            "light_type": light_data.type,
            "shadow_settings": applied,
        })
    except Exception as e:
        return error_response(f"Failed to apply shadow settings to '{name}': {e}")


# ─── Register routes ────────────────────────────────────────────────────────────

register_handler("light", "create", _handle_light_create)
register_handler("light", "configure", _handle_light_configure)
register_handler("light", "sun-setup", _handle_light_sun_setup)
register_handler("light", "three-point", _handle_light_three_point)
register_handler("light", "hdri-setup", _handle_light_hdri_setup)
register_handler("light", "world-color", _handle_light_world_color)
register_handler("light", "list", _handle_light_list)
register_handler("light", "shadow-settings", _handle_light_shadow_settings)
