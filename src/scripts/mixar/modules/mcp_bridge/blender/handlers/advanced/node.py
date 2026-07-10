"""
Advanced node handlers for Blender MCP Bridge.
Provides: node/list, node/add, node/remove, node/connect, node/disconnect,
          node/set-value, node/group-create, node/group-add-io,
          node/geonodes-create, node/geonodes-set-input,
          node/tree-info, node/arrange, node/colorramp-set
"""

import bpy
from ...utils.response import ok_response, error_response, not_found
from ...utils.context_helpers import ensure_context_for_object, temp_override, safe_operator_call
from .. import register_handler


# ─── Tree-owner resolution helper ────────────────────────────────────────────────

def _resolve_node_tree(tree_owner):
    """
    Resolve a tree_owner string to a (node_tree, error_or_None) pair.

    Conventions:
      "COMPOSITING"          → bpy.context.scene.node_tree (compositor)
      "object:ObjectName"    → first NODES modifier on the named object
      plain string           → try as material name, then as node_group name
    """
    if not tree_owner:
        return None, error_response("Parameter 'tree_owner' is required.")

    # ── Compositor ─────────────────────────────────────────────────────────────
    if tree_owner.upper() == "COMPOSITING":
        bpy.context.scene.use_nodes = True
        tree = bpy.context.scene.node_tree
        if tree is None:
            return None, error_response("Could not create or access the compositor node tree.")
        return tree, None

    # ── Object (Geometry Nodes) ─────────────────────────────────────────────────
    if tree_owner.lower().startswith("object:"):
        obj_name = tree_owner[len("object:"):]
        obj = bpy.data.objects.get(obj_name)
        if obj is None:
            return None, not_found(obj_name, "Node tree owner")
        for mod in obj.modifiers:
            if mod.type == "NODES" and mod.node_group is not None:
                return mod.node_group, None
        return None, error_response(
            f"Object '{obj_name}' has no Geometry Nodes modifier with an assigned node group."
        )

    # ── Material (shader node tree) ─────────────────────────────────────────────
    mat = bpy.data.materials.get(tree_owner)
    if mat is not None:
        mat.use_nodes = True
        tree = mat.node_tree
        if tree is None:
            return None, error_response(
                f"Could not access the node tree of material '{tree_owner}'."
            )
        return tree, None

    # ── Bare node_group name ────────────────────────────────────────────────────
    group = bpy.data.node_groups.get(tree_owner)
    if group is not None:
        return group, None

    return None, error_response(
        f"Could not resolve tree_owner '{tree_owner}'. "
        "Expected a material name, 'COMPOSITING', 'object:ObjectName', or a node_group name."
    )


# ─── Socket access helper ─────────────────────────────────────────────────────────

def _get_socket(node, socket_ref, collection, _match_info=None):
    """
    Return a socket from `collection` (node.inputs or node.outputs).
    socket_ref can be a string name or an integer index.

    If _match_info is a dict, it will be populated with fuzzy match details
    when the socket is resolved via case-insensitive fallback:
        {"requested": original_ref, "matched": actual_name}
    """
    if isinstance(socket_ref, int):
        if socket_ref < 0 or socket_ref >= len(collection):
            raise IndexError(
                f"Socket index {socket_ref} is out of range "
                f"(node '{node.name}' has {len(collection)} sockets in this direction)."
            )
        return collection[socket_ref]
    # String name — try direct lookup first, then iterate for case-insensitive match
    if socket_ref in collection:
        return collection[socket_ref]
    socket_ref_lower = socket_ref.lower()
    for s in collection:
        if s.name.lower() == socket_ref_lower:
            if isinstance(_match_info, dict):
                _match_info["requested"] = socket_ref
                _match_info["matched"] = s.name
            return s
    raise KeyError(
        f"Socket '{socket_ref}' not found on node '{node.name}'. "
        f"Available: {[s.name for s in collection]}"
    )


# ─── Handlers ─────────────────────────────────────────────────────────────────────

def _handle_node_list(params):
    """
    List all nodes in a node tree.
    Route: node/list
    """
    tree_owner = params.get("tree_owner")
    tree, err = _resolve_node_tree(tree_owner)
    if err:
        return err

    try:
        nodes_info = []
        for node in tree.nodes:
            nodes_info.append({
                "name": node.name,
                "type": node.bl_idname,
                "location": [round(node.location.x, 2), round(node.location.y, 2)],
                "inputs": [s.name for s in node.inputs],
                "outputs": [s.name for s in node.outputs],
            })
        return ok_response({
            "tree_owner": tree_owner,
            "node_count": len(nodes_info),
            "nodes": nodes_info,
        })
    except Exception as e:
        return error_response(f"Failed to list nodes for '{tree_owner}': {e}")


def _handle_node_add(params):
    """
    Add a new node to a node tree.
    Route: node/add
    """
    tree_owner = params.get("tree_owner")
    node_type = params.get("node_type")
    location = params.get("location")

    if not node_type:
        return error_response("Parameter 'node_type' is required.")

    tree, err = _resolve_node_tree(tree_owner)
    if err:
        return err

    try:
        node = tree.nodes.new(node_type)
    except Exception as e:
        return error_response(
            f"Failed to create node of type '{node_type}' in tree '{tree_owner}': {e}"
        )

    try:
        if location is not None:
            node.location = (float(location[0]), float(location[1]))

        # Apply user-specified name to node name and label
        node.name = params.get("name", node.name)
        if params.get("name"):
            node.label = params.get("name", "")

        return ok_response({
            "tree_owner": tree_owner,
            "name": node.name,
            "type": node.bl_idname,
            "location": [round(node.location.x, 2), round(node.location.y, 2)],
        })
    except Exception as e:
        return error_response(f"Node created but post-creation setup failed: {e}")


def _handle_node_remove(params):
    """
    Remove a node from a node tree by name.
    Route: node/remove
    """
    tree_owner = params.get("tree_owner")
    node_name = params.get("node_name")

    if not node_name:
        return error_response("Parameter 'node_name' is required.")

    tree, err = _resolve_node_tree(tree_owner)
    if err:
        return err

    node = tree.nodes.get(node_name)
    if node is None:
        return error_response(
            f"Node '{node_name}' not found in tree '{tree_owner}'. "
            f"Available nodes: {[n.name for n in tree.nodes]}"
        )

    try:
        tree.nodes.remove(node)
        return ok_response({
            "tree_owner": tree_owner,
            "removed_node": node_name,
        })
    except Exception as e:
        return error_response(f"Failed to remove node '{node_name}': {e}")


def _handle_node_connect(params):
    """
    Connect an output socket to an input socket across two nodes.
    Route: node/connect
    """
    tree_owner = params.get("tree_owner")
    from_node_name = params.get("from_node")
    from_socket_ref = params.get("from_socket")
    to_node_name = params.get("to_node")
    to_socket_ref = params.get("to_socket")

    for param, val in [("from_node", from_node_name), ("from_socket", from_socket_ref),
                       ("to_node", to_node_name), ("to_socket", to_socket_ref)]:
        if val is None:
            return error_response(f"Parameter '{param}' is required.")

    tree, err = _resolve_node_tree(tree_owner)
    if err:
        return err

    from_node = tree.nodes.get(from_node_name)
    if from_node is None:
        return error_response(f"Source node '{from_node_name}' not found in tree '{tree_owner}'.")

    to_node = tree.nodes.get(to_node_name)
    if to_node is None:
        return error_response(f"Destination node '{to_node_name}' not found in tree '{tree_owner}'.")

    try:
        # Support integer index passed as a number from JSON
        if isinstance(from_socket_ref, float):
            from_socket_ref = int(from_socket_ref)
        if isinstance(to_socket_ref, float):
            to_socket_ref = int(to_socket_ref)

        from_match_info = {}
        to_match_info = {}
        from_socket = _get_socket(from_node, from_socket_ref, from_node.outputs, _match_info=from_match_info)
        to_socket = _get_socket(to_node, to_socket_ref, to_node.inputs, _match_info=to_match_info)
    except (KeyError, IndexError) as e:
        return error_response(str(e))

    try:
        tree.links.new(from_socket, to_socket)

        # Build warnings for any fuzzy-matched socket names
        warnings = []
        if from_match_info:
            warnings.append(
                f"Socket '{from_match_info['requested']}' not found, matched '{from_match_info['matched']}' instead"
            )
        if to_match_info:
            warnings.append(
                f"Socket '{to_match_info['requested']}' not found, matched '{to_match_info['matched']}' instead"
            )

        result = {
            "tree_owner": tree_owner,
            "from_node": from_node_name,
            "from_socket": from_socket.name,
            "to_node": to_node_name,
            "to_socket": to_socket.name,
        }
        if warnings:
            result["warning"] = "; ".join(warnings)

        return ok_response(result)
    except Exception as e:
        return error_response(
            f"Failed to create link from '{from_node_name}'.'{from_socket.name}' "
            f"to '{to_node_name}'.'{to_socket.name}': {e}"
        )


def _handle_node_disconnect(params):
    """
    Remove all links connected to a specific socket on a node.
    Route: node/disconnect
    """
    tree_owner = params.get("tree_owner")
    node_name = params.get("node_name")
    socket_ref = params.get("socket_name")
    direction = params.get("direction", "INPUT").upper()

    if not node_name:
        return error_response("Parameter 'node_name' is required.")
    if socket_ref is None:
        return error_response("Parameter 'socket_name' is required.")
    if direction not in ("INPUT", "OUTPUT"):
        return error_response("Parameter 'direction' must be 'INPUT' or 'OUTPUT'.")

    tree, err = _resolve_node_tree(tree_owner)
    if err:
        return err

    node = tree.nodes.get(node_name)
    if node is None:
        return error_response(f"Node '{node_name}' not found in tree '{tree_owner}'.")

    try:
        if isinstance(socket_ref, float):
            socket_ref = int(socket_ref)
        collection = node.inputs if direction == "INPUT" else node.outputs
        socket = _get_socket(node, socket_ref, collection)
    except (KeyError, IndexError) as e:
        return error_response(str(e))

    try:
        links_to_remove = [lnk for lnk in tree.links
                           if (direction == "INPUT" and lnk.to_socket == socket) or
                              (direction == "OUTPUT" and lnk.from_socket == socket)]
        removed_count = len(links_to_remove)
        for lnk in links_to_remove:
            tree.links.remove(lnk)

        return ok_response({
            "tree_owner": tree_owner,
            "node_name": node_name,
            "socket_name": socket.name,
            "direction": direction,
            "links_removed": removed_count,
        })
    except Exception as e:
        return error_response(f"Failed to disconnect socket '{socket_ref}' on '{node_name}': {e}")


def _handle_node_set_value(params):
    """
    Set the default value of an input socket on a node.
    Route: node/set-value
    """
    tree_owner = params.get("tree_owner")
    node_name = params.get("node_name")
    input_name = params.get("input_name")
    value = params.get("value")

    if not node_name:
        return error_response("Parameter 'node_name' is required.")
    if not input_name:
        return error_response("Parameter 'input_name' is required.")
    if value is None:
        return error_response("Parameter 'value' is required.")

    tree, err = _resolve_node_tree(tree_owner)
    if err:
        return err

    node = tree.nodes.get(node_name)
    if node is None:
        return error_response(f"Node '{node_name}' not found in tree '{tree_owner}'.")

    try:
        socket = _get_socket(node, input_name, node.inputs)
    except (KeyError, IndexError) as e:
        return error_response(str(e))

    try:
        if isinstance(value, list):
            if len(value) == 4:
                socket.default_value = (
                    float(value[0]), float(value[1]),
                    float(value[2]), float(value[3])
                )
            elif len(value) == 3:
                socket.default_value = (
                    float(value[0]), float(value[1]), float(value[2])
                )
            else:
                return error_response(
                    f"List value must have 3 (vector/RGB) or 4 (RGBA) elements, "
                    f"got {len(value)}."
                )
        else:
            socket.default_value = value

        # Retrieve the stored value for confirmation (may differ for clamped types)
        try:
            stored = list(socket.default_value) if hasattr(socket.default_value, "__iter__") \
                else socket.default_value
        except Exception:
            stored = value

        return ok_response({
            "tree_owner": tree_owner,
            "node_name": node_name,
            "input_name": socket.name,
            "value_set": stored,
        })
    except Exception as e:
        return error_response(
            f"Failed to set value on socket '{input_name}' of node '{node_name}': {e}"
        )


def _handle_node_group_create(params):
    """
    Create a new reusable node group datablock.
    Route: node/group-create
    """
    name = params.get("name")
    tree_type_key = params.get("tree_type", "").upper()

    if not name:
        return error_response("Parameter 'name' is required.")
    if not tree_type_key:
        return error_response("Parameter 'tree_type' is required.")

    tree_type_map = {
        "SHADER": "ShaderNodeTree",
        "GEOMETRY": "GeometryNodeTree",
        "COMPOSITING": "CompositorNodeTree",
    }
    tree_type_str = tree_type_map.get(tree_type_key)
    if tree_type_str is None:
        return error_response(
            f"Unknown tree_type '{tree_type_key}'. "
            f"Valid: {', '.join(tree_type_map.keys())}."
        )

    try:
        group = bpy.data.node_groups.new(name, tree_type_str)
        return ok_response({
            "name": group.name,
            "tree_type": tree_type_key,
            "bl_idname": group.bl_idname,
        })
    except Exception as e:
        return error_response(f"Failed to create node group '{name}': {e}")


def _handle_node_group_add_io(params):
    """
    Add an input or output socket to a node group's interface.
    Supports both Blender 4.x (interface.new_socket) and 3.x (inputs/outputs.new).
    Route: node/group-add-io
    """
    group_name = params.get("group_name")
    direction = params.get("direction", "").upper()
    socket_type = params.get("socket_type")
    socket_name = params.get("name")

    if not group_name:
        return error_response("Parameter 'group_name' is required.")
    if direction not in ("INPUT", "OUTPUT"):
        return error_response("Parameter 'direction' must be 'INPUT' or 'OUTPUT'.")
    if not socket_type:
        return error_response("Parameter 'socket_type' is required.")
    if not socket_name:
        return error_response("Parameter 'name' is required.")

    group = bpy.data.node_groups.get(group_name)
    if group is None:
        return error_response(
            f"Node group '{group_name}' not found in bpy.data.node_groups."
        )

    try:
        # Blender 4.x: interface.new_socket
        try:
            socket = group.interface.new_socket(
                name=socket_name,
                in_out=direction,
                socket_type=socket_type,
            )
            socket_added_name = socket.name
        except AttributeError:
            # Blender 3.x fallback: use inputs/outputs collections
            if direction == "INPUT":
                socket = group.inputs.new(socket_type, socket_name)
            else:
                socket = group.outputs.new(socket_type, socket_name)
            socket_added_name = socket.name

        return ok_response({
            "group_name": group.name,
            "direction": direction,
            "socket_type": socket_type,
            "socket_name": socket_added_name,
        })
    except Exception as e:
        return error_response(
            f"Failed to add {direction} socket '{socket_name}' "
            f"of type '{socket_type}' to group '{group_name}': {e}"
        )


def _handle_node_geonodes_create(params):
    """
    Add a Geometry Nodes modifier to an object and initialise its node group.
    Route: node/geonodes-create
    """
    object_name = params.get("object_name")
    name = params.get("name") or "GeometryNodes"

    if not object_name:
        return error_response("Parameter 'object_name' is required.")

    obj = bpy.data.objects.get(object_name)
    if obj is None:
        return not_found(object_name)

    try:
        # Add the Geometry Nodes modifier  # object_name lookup — default entity OK
        mod = obj.modifiers.new(name, "NODES")

        # Create and assign a fresh node group
        group = bpy.data.node_groups.new(name, "GeometryNodeTree")
        mod.node_group = group

        # Add Group Input and Group Output nodes
        input_node = group.nodes.new("NodeGroupInput")
        output_node = group.nodes.new("NodeGroupOutput")

        # Position them for readability
        input_node.location = (-200.0, 0.0)
        output_node.location = (200.0, 0.0)

        # Try to add a Geometry interface socket and connect the pass-through link.
        # Blender 4.x uses interface.new_socket; fall back to 3.x inputs/outputs.
        try:
            group.interface.new_socket(
                name="Geometry",
                in_out="INPUT",
                socket_type="NodeSocketGeometry",
            )
            group.interface.new_socket(
                name="Geometry",
                in_out="OUTPUT",
                socket_type="NodeSocketGeometry",
            )
        except AttributeError:
            group.inputs.new("NodeSocketGeometry", "Geometry")
            group.outputs.new("NodeSocketGeometry", "Geometry")

        # Connect Geometry output of GroupInput → Geometry input of GroupOutput
        try:
            group.links.new(
                input_node.outputs["Geometry"],
                output_node.inputs["Geometry"],
            )
        except Exception:
            # Sockets may not be present on older builds; this is best-effort
            pass

        return ok_response({
            "object_name": obj.name,
            "modifier_name": mod.name,
            "node_group_name": group.name,
        })
    except Exception as e:
        return error_response(
            f"Failed to create Geometry Nodes setup on '{object_name}': {e}"
        )


def _handle_node_geonodes_set_input(params):
    """
    Set a Geometry Nodes modifier input value on an object.
    Route: node/geonodes-set-input
    """
    object_name = params.get("object_name")
    modifier_name = params.get("modifier_name")
    input_name = params.get("input_name")
    value = params.get("value")

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if not modifier_name:
        return error_response("Parameter 'modifier_name' is required.")
    if not input_name:
        return error_response("Parameter 'input_name' is required.")
    if value is None:
        return error_response("Parameter 'value' is required.")

    obj = bpy.data.objects.get(object_name)
    if obj is None:
        return not_found(object_name)

    mod = obj.modifiers.get(modifier_name)
    if mod is None:
        return error_response(
            f"Modifier '{modifier_name}' not found on object '{object_name}'. "
            f"Available modifiers: {[m.name for m in obj.modifiers]}"
        )
    if mod.type != "NODES":
        return error_response(
            f"Modifier '{modifier_name}' is of type '{mod.type}', not 'NODES'."
        )

    try:
        if isinstance(value, list):
            value = tuple(value)
        mod[input_name] = value
        return ok_response({
            "object_name": obj.name,
            "modifier_name": mod.name,
            "input_name": input_name,
            "value_set": value,
        })
    except Exception as e:
        return error_response(
            f"Failed to set input '{input_name}' on modifier '{modifier_name}' "
            f"of object '{object_name}': {e}"
        )


def _handle_node_tree_info(params):
    """
    Return detailed information about a node tree: nodes, links, counts.
    Route: node/tree-info
    """
    tree_owner = params.get("tree_owner")
    tree, err = _resolve_node_tree(tree_owner)
    if err:
        return err

    try:
        nodes_info = []
        for node in tree.nodes:
            nodes_info.append({
                "name": node.name,
                "type": node.bl_idname,
                "location": [round(node.location.x, 2), round(node.location.y, 2)],
            })

        links_info = []
        for lnk in tree.links:
            links_info.append({
                "from_node": lnk.from_node.name,
                "from_socket": lnk.from_socket.name,
                "to_node": lnk.to_node.name,
                "to_socket": lnk.to_socket.name,
            })

        return ok_response({
            "tree_owner": tree_owner,
            "node_count": len(nodes_info),
            "link_count": len(links_info),
            "nodes": nodes_info,
            "links": links_info,
        })
    except Exception as e:
        return error_response(f"Failed to retrieve tree info for '{tree_owner}': {e}")


def _handle_node_arrange(params):
    """
    Auto-arrange nodes in a node tree using BFS from the output node.
    Route: node/arrange
    """
    tree_owner = params.get("tree_owner")
    tree, err = _resolve_node_tree(tree_owner)
    if err:
        return err

    H_SPACING = 250.0   # horizontal gap between columns
    V_SPACING = 100.0   # vertical gap between rows in the same column

    try:
        nodes = list(tree.nodes)
        if not nodes:
            return ok_response({"tree_owner": tree_owner, "nodes_arranged": 0})

        # Build adjacency: for each node, which nodes feed into it (predecessors)?
        # We need to walk links: link.to_node depends on link.from_node.
        predecessors = {n.name: set() for n in nodes}
        for lnk in tree.links:
            predecessors[lnk.to_node.name].add(lnk.from_node.name)

        # Find root/output nodes (nodes with no outgoing links used as input by others)
        successor_set = {lnk.from_node.name for lnk in tree.links}
        output_nodes = [n for n in nodes if n.name not in successor_set]
        if not output_nodes:
            # Fallback: pick any node as root
            output_nodes = [nodes[0]]

        # BFS assigns a "depth" (column) to each node.
        # Output nodes are at depth 0; their predecessors at depth 1, etc.
        depth = {}
        from collections import deque
        queue = deque()
        for root in output_nodes:
            if root.name not in depth:
                depth[root.name] = 0
                queue.append(root)

        # Also enqueue any nodes not yet reached
        for n in nodes:
            if n.name not in depth:
                depth[n.name] = 0
                queue.append(n)

        # BFS to propagate depth via predecessor links
        visited = set()
        bfs_queue = deque()
        for root in output_nodes:
            bfs_queue.append(root.name)
            visited.add(root.name)
            depth[root.name] = 0

        while bfs_queue:
            current_name = bfs_queue.popleft()
            current_depth = depth[current_name]
            for pred_name in predecessors.get(current_name, set()):
                new_depth = current_depth + 1
                if pred_name not in visited or depth.get(pred_name, 0) < new_depth:
                    depth[pred_name] = new_depth
                    visited.add(pred_name)
                    bfs_queue.append(pred_name)

        # Handle any nodes not reached by BFS
        max_depth = max(depth.values()) if depth else 0
        for n in nodes:
            if n.name not in depth:
                max_depth += 1
                depth[n.name] = max_depth

        # Group nodes by depth column
        columns = {}
        for n in nodes:
            col = depth[n.name]
            columns.setdefault(col, []).append(n)

        # Sort within each column by existing Y for stability
        for col_nodes in columns.values():
            col_nodes.sort(key=lambda n: -n.location.y)

        # Assign positions — depth 0 (outputs) on the right, increasing depth moves left
        max_col = max(columns.keys()) if columns else 0
        for col_idx, col_nodes in columns.items():
            x = (max_col - col_idx) * H_SPACING
            for row_idx, node in enumerate(col_nodes):
                node.location.x = x
                node.location.y = -row_idx * V_SPACING

        return ok_response({
            "tree_owner": tree_owner,
            "nodes_arranged": len(nodes),
        })
    except Exception as e:
        return error_response(f"Failed to arrange nodes for '{tree_owner}': {e}")


def _handle_node_colorramp_set(params):
    """
    Configure the color stops of a ColorRamp node in a material.
    Route: node/colorramp-set
    """
    material_name = params.get("material_name")
    node_name = params.get("node_name")
    stops = params.get("stops")

    if not material_name:
        return error_response("Parameter 'material_name' is required.")
    if not node_name:
        return error_response("Parameter 'node_name' is required.")
    if not stops or not isinstance(stops, list):
        return error_response("Parameter 'stops' is required and must be an array.")

    if len(stops) == 0:
        return error_response("At least one stop is required.")

    # Validate each stop before touching the node tree
    warnings = []
    for i, stop in enumerate(stops):
        if "position" not in stop:
            return error_response(
                f"Stop at index {i} is missing required key 'position'."
            )
        if "color" not in stop:
            return error_response(
                f"Stop at index {i} is missing required key 'color'."
            )

        # Validate position is a number and clamp to [0.0, 1.0]
        pos = stop["position"]
        if not isinstance(pos, (int, float)):
            return error_response(
                f"Stop at index {i}: 'position' must be a number, got {type(pos).__name__}."
            )
        if pos < 0.0 or pos > 1.0:
            clamped = max(0.0, min(1.0, float(pos)))
            warnings.append(
                f"Stop at index {i}: position {pos} clamped to {clamped}."
            )
            stop["position"] = clamped

        # Validate color is a list/tuple of exactly 4 numbers [r,g,b,a]
        color = stop["color"]
        if not isinstance(color, (list, tuple)):
            return error_response(
                f"Stop at index {i}: 'color' must be an array, got {type(color).__name__}."
            )
        if len(color) != 4:
            return error_response(
                f"Stop at index {i}: 'color' must have exactly 4 elements [r, g, b, a], "
                f"got {len(color)}."
            )
        for ci, component in enumerate(color):
            if not isinstance(component, (int, float)):
                return error_response(
                    f"Stop at index {i}: 'color[{ci}]' must be a number, "
                    f"got {type(component).__name__}."
                )

    mat = bpy.data.materials.get(material_name)
    if mat is None:
        return not_found(material_name, "Material")

    mat.use_nodes = True
    tree = mat.node_tree
    if tree is None:
        return error_response(
            f"Could not access the node tree of material '{material_name}'."
        )

    node = tree.nodes.get(node_name)
    if node is None:
        return error_response(
            f"Node '{node_name}' not found in material '{material_name}'. "
            f"Available nodes: {[n.name for n in tree.nodes]}"
        )

    if node.type != 'VALTORGB':
        return error_response(
            f"Node '{node_name}' is of type '{node.type}', not 'VALTORGB' (ColorRamp). "
            "This tool only works on ColorRamp nodes."
        )

    try:
        color_ramp = node.color_ramp
        elements = color_ramp.elements

        # Remove all elements except the first (Blender requires at least 1)
        while len(elements) > 1:
            elements.remove(elements[-1])

        # Configure the first stop
        first_stop = stops[0]
        elements[0].position = float(first_stop["position"])
        c = first_stop["color"]
        elements[0].color = (float(c[0]), float(c[1]), float(c[2]), float(c[3]))

        # Add remaining stops
        for stop_def in stops[1:]:
            elem = elements.new(float(stop_def["position"]))
            sc = stop_def["color"]
            elem.color = (float(sc[0]), float(sc[1]), float(sc[2]), float(sc[3]))

        # Build result
        configured = []
        for elem in elements:
            configured.append({
                "position": round(elem.position, 4),
                "color": [round(elem.color[0], 4), round(elem.color[1], 4),
                          round(elem.color[2], 4), round(elem.color[3], 4)],
            })

        result = {
            "material_name": material_name,
            "node_name": node_name,
            "stops_configured": len(configured),
            "stops": configured,
        }
        if warnings:
            result["warning"] = "; ".join(warnings)

        return ok_response(result)
    except Exception as e:
        return error_response(
            f"Failed to configure ColorRamp stops on node '{node_name}' "
            f"in material '{material_name}': {e}"
        )


# ─── Register routes ──────────────────────────────────────────────────────────────

register_handler("node", "list",               _handle_node_list)
register_handler("node", "add",                _handle_node_add)
register_handler("node", "remove",             _handle_node_remove)
register_handler("node", "connect",            _handle_node_connect)
register_handler("node", "disconnect",         _handle_node_disconnect)
register_handler("node", "set-value",          _handle_node_set_value)
register_handler("node", "group-create",       _handle_node_group_create)
register_handler("node", "group-add-io",       _handle_node_group_add_io)
register_handler("node", "geonodes-create",    _handle_node_geonodes_create)
register_handler("node", "geonodes-set-input", _handle_node_geonodes_set_input)
register_handler("node", "tree-info",          _handle_node_tree_info)
register_handler("node", "arrange",            _handle_node_arrange)
register_handler("node", "colorramp-set",      _handle_node_colorramp_set)
