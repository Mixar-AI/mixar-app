// Advanced node tools — node tree manipulation, shader nodes, geometry nodes

import { sendToBlender } from "../../blender-bridge.js";

export const nodeTools = [
  {
    name: "blender_node_list",
    description:
      "List all nodes in a node tree identified by tree_owner. " +
      "For shader/material trees, pass the material name as tree_owner (e.g. 'MyMaterial'). " +
      "For the scene compositor, pass 'COMPOSITING'. " +
      "For a geometry nodes group on an object, pass 'object:ObjectName'. " +
      "Returns each node's name, type (bl_idname), location [x, y], and a summary of its " +
      "input and output socket names so you can plan connections. " +
      "Example call: { \"tree_owner\": \"MyMaterial\" }.",
    inputSchema: {
      type: "object",
      properties: {
        tree_owner: {
          type: "string",
          description:
            "Identifies the node tree: a material name, 'COMPOSITING', " +
            "'object:ObjectName' for the first GeometryNodes modifier on an object, " +
            "or a bare node_group name.",
        },
      },
      required: ["tree_owner"],
    },
    handler: async (args) => {
      const result = await sendToBlender("node/list", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_node_add",
    description:
      "Add a new node to a node tree. " +
      "tree_owner identifies the node tree using the same convention as blender_node_list. " +
      "node_type must be a valid Blender bl_idname such as 'ShaderNodeBsdfPrincipled', " +
      "'ShaderNodeTexImage', 'GeometryNodeMeshCube', 'CompositorNodeBlur', etc. " +
      "An optional location [x, y] sets the node's position in the node editor canvas. " +
      "Returns the new node's name, type, and assigned location. " +
      "Example call: { \"tree_owner\": \"MyMaterial\", \"node_type\": \"ShaderNodeTexImage\", \"location\": [-300, 200] }.",
    inputSchema: {
      type: "object",
      properties: {
        tree_owner: {
          type: "string",
          description:
            "Identifies the node tree: material name, 'COMPOSITING', " +
            "'object:ObjectName', or a node_group name.",
        },
        node_type: {
          type: "string",
          description:
            "The bl_idname of the node to create, e.g. 'ShaderNodeBsdfPrincipled'.",
        },
        location: {
          type: "array",
          items: { type: "number" },
          minItems: 2,
          maxItems: 2,
          description:
            "Optional [x, y] position in the node editor canvas. " +
            "IMPORTANT: Must be a JSON array of 2 numbers, NOT a string. " +
            "Example: [-200, 300].",
        },
      },
      required: ["tree_owner", "node_type"],
    },
    handler: async (args) => {
      const result = await sendToBlender("node/add", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_node_remove",
    description:
      "Remove a node from a node tree by name. " +
      "All links connected to the node are automatically removed as well. " +
      "tree_owner identifies the node tree using the same convention as blender_node_list. " +
      "node_name must exactly match the node's name as returned by blender_node_list. " +
      "Returns the name of the node that was removed. " +
      "Example call: { \"tree_owner\": \"MyMaterial\", \"node_name\": \"Image Texture\" }.",
    inputSchema: {
      type: "object",
      properties: {
        tree_owner: {
          type: "string",
          description:
            "Identifies the node tree: material name, 'COMPOSITING', " +
            "'object:ObjectName', or a node_group name.",
        },
        node_name: {
          type: "string",
          description: "Exact name of the node to remove.",
        },
      },
      required: ["tree_owner", "node_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("node/remove", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_node_connect",
    description:
      "Connect an output socket of one node to an input socket of another node. " +
      "tree_owner identifies the node tree. from_node and to_node are node names. " +
      "from_socket and to_socket can each be a socket name (e.g. 'Base Color') or " +
      "an integer index. Connecting sockets of compatible types creates a data link; " +
      "incompatible types may be silently ignored by Blender. " +
      "Returns the from/to node and socket names that were linked. " +
      "Example call: { \"tree_owner\": \"MyMaterial\", \"from_node\": \"Image Texture\", \"from_socket\": \"Color\", \"to_node\": \"Principled BSDF\", \"to_socket\": \"Base Color\" }.",
    inputSchema: {
      type: "object",
      properties: {
        tree_owner: {
          type: "string",
          description:
            "Identifies the node tree: material name, 'COMPOSITING', " +
            "'object:ObjectName', or a node_group name.",
        },
        from_node: {
          type: "string",
          description: "Name of the source node.",
        },
        from_socket: {
          type: "string",
          description: "Output socket name (string) or index (integer) on the source node.",
        },
        to_node: {
          type: "string",
          description: "Name of the destination node.",
        },
        to_socket: {
          type: "string",
          description: "Input socket name (string) or index (integer) on the destination node.",
        },
      },
      required: ["tree_owner", "from_node", "from_socket", "to_node", "to_socket"],
    },
    handler: async (args) => {
      const result = await sendToBlender("node/connect", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_node_disconnect",
    description:
      "Remove all links connected to a specific socket on a node. " +
      "tree_owner identifies the node tree, node_name is the node, " +
      "and socket_name identifies which socket to disconnect (by name or index). " +
      "direction controls whether an INPUT or OUTPUT socket is targeted (default INPUT). " +
      "All links attached to the named socket are removed. " +
      "Returns how many links were removed. " +
      "Example call: { \"tree_owner\": \"MyMaterial\", \"node_name\": \"Principled BSDF\", \"socket_name\": \"Base Color\", \"direction\": \"INPUT\" }.",
    inputSchema: {
      type: "object",
      properties: {
        tree_owner: {
          type: "string",
          description:
            "Identifies the node tree: material name, 'COMPOSITING', " +
            "'object:ObjectName', or a node_group name.",
        },
        node_name: {
          type: "string",
          description: "Name of the node whose socket links to remove.",
        },
        socket_name: {
          type: "string",
          description: "Socket name (string) or index (integer) to disconnect.",
        },
        direction: {
          type: "string",
          enum: ["INPUT", "OUTPUT"],
          description: "Whether to target an input or output socket (default INPUT). Must be UPPERCASE.",
        },
      },
      required: ["tree_owner", "node_name", "socket_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("node/disconnect", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_node_set_value",
    description:
      "Set the default value of an input socket on a node. " +
      "This is used to set unconnected socket values such as a shader's Roughness, " +
      "a color input (pass a 4-element RGBA array), a vector (3-element array), " +
      "or a scalar float/int. " +
      "tree_owner identifies the node tree, node_name is the node, " +
      "input_name is the socket name (e.g. 'Roughness', 'Base Color'). " +
      "Returns the socket name and the value that was applied. " +
      "Example call: { \"tree_owner\": \"MyMaterial\", \"node_name\": \"Principled BSDF\", \"input_name\": \"Roughness\", \"value\": 0.3 }.",
    inputSchema: {
      type: "object",
      properties: {
        tree_owner: {
          type: "string",
          description:
            "Identifies the node tree: material name, 'COMPOSITING', " +
            "'object:ObjectName', or a node_group name.",
        },
        node_name: {
          type: "string",
          description: "Name of the node containing the input socket.",
        },
        input_name: {
          type: "string",
          description: "Name of the input socket whose default value to set.",
        },
        value: {
          oneOf: [
            { type: "number" },
            { type: "array", items: { type: "number" }, minItems: 3, maxItems: 4 },
          ],
          description:
            "The value to assign. Use a number for scalar inputs, " +
            "a 3-element array for vector/color-RGB inputs, " +
            "or a 4-element array for RGBA color inputs. " +
            "IMPORTANT: Arrays must be JSON arrays of numbers, NOT strings. " +
            "Example (scalar): 0.5. Example (color): [1.0, 0.0, 0.0, 1.0].",
        },
      },
      required: ["tree_owner", "node_name", "input_name", "value"],
    },
    handler: async (args) => {
      const result = await sendToBlender("node/set-value", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_node_group_create",
    description:
      "Create a new reusable node group (node_group datablock) of the specified tree type. " +
      "SHADER creates a ShaderNodeTree group for use in material node trees. " +
      "GEOMETRY creates a GeometryNodeTree group suitable for geometry node modifiers. " +
      "COMPOSITING creates a CompositorNodeTree group for the compositor. " +
      "The new group appears in bpy.data.node_groups and can be instanced with a Group node. " +
      "Returns the group name and its tree type. " +
      "Example call: { \"name\": \"MyShaderGroup\", \"tree_type\": \"SHADER\" }.",
    inputSchema: {
      type: "object",
      properties: {
        name: {
          type: "string",
          description: "Name for the new node group datablock.",
        },
        tree_type: {
          type: "string",
          enum: ["SHADER", "GEOMETRY", "COMPOSITING"],
          description:
            "Tree type. Must be UPPERCASE. SHADER for material shader groups, " +
            "GEOMETRY for geometry node groups, COMPOSITING for compositor groups.",
        },
      },
      required: ["name", "tree_type"],
    },
    handler: async (args) => {
      const result = await sendToBlender("node/group-create", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_node_group_add_io",
    description:
      "Add an input or output socket to an existing node group's interface. " +
      "group_name must be an existing node group in bpy.data.node_groups. " +
      "direction is INPUT or OUTPUT. " +
      "socket_type is a Blender socket type identifier such as 'NodeSocketFloat', " +
      "'NodeSocketColor', 'NodeSocketVector', 'NodeSocketGeometry', 'NodeSocketBool', etc. " +
      "name is the display name for the new socket. " +
      "Supports both Blender 4.x (interface.new_socket) and 3.x (inputs/outputs.new) APIs. " +
      "Returns the group name, direction, socket type, and socket name added. " +
      "Example call: { \"group_name\": \"MyShaderGroup\", \"direction\": \"INPUT\", \"socket_type\": \"NodeSocketFloat\", \"name\": \"Factor\" }.",
    inputSchema: {
      type: "object",
      properties: {
        group_name: {
          type: "string",
          description: "Name of an existing node group in bpy.data.node_groups.",
        },
        direction: {
          type: "string",
          enum: ["INPUT", "OUTPUT"],
          description: "Whether to add an input or output socket to the group interface. Must be UPPERCASE.",
        },
        socket_type: {
          type: "string",
          description:
            "Socket type identifier, e.g. 'NodeSocketFloat', 'NodeSocketColor', " +
            "'NodeSocketVector', 'NodeSocketGeometry', 'NodeSocketBool', 'NodeSocketInt'.",
        },
        name: {
          type: "string",
          description: "Display name for the new socket.",
        },
      },
      required: ["group_name", "direction", "socket_type", "name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("node/group-add-io", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_node_geonodes_create",
    description:
      "Add a Geometry Nodes modifier to an object and set up a fresh node group for it. " +
      "The modifier is named using the name parameter (or 'GeometryNodes' if omitted). " +
      "A new GeometryNodeTree group is created and assigned to the modifier. " +
      "Group Input and Group Output nodes are automatically added to the tree, " +
      "and their Geometry sockets are connected so the object passes through by default. " +
      "Returns the object name, modifier name, and node group name. " +
      "Example call: { \"object_name\": \"Cube\", \"name\": \"ScatterGrass\" }.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the object to add the Geometry Nodes modifier to.",
        },
        name: {
          type: "string",
          description:
            "Optional name for both the modifier and the new node group " +
            "(defaults to 'GeometryNodes').",
        },
      },
      required: ["object_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("node/geonodes-create", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_node_geonodes_set_input",
    description:
      "Set a Geometry Nodes modifier input value on an object. " +
      "This writes directly to the modifier's socket value store — " +
      "equivalent to setting the socket value in the modifier properties panel. " +
      "object_name is the object, modifier_name is the exact modifier name, " +
      "input_name is the socket/input identifier (e.g. the name of a group input socket), " +
      "and value is the value to assign (number, boolean, or array). " +
      "Returns the object name, modifier name, and the input that was set. " +
      "Example call: { \"object_name\": \"Cube\", \"modifier_name\": \"GeometryNodes\", \"input_name\": \"Density\", \"value\": 5.0 }.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the object that owns the Geometry Nodes modifier.",
        },
        modifier_name: {
          type: "string",
          description: "Exact name of the Geometry Nodes modifier.",
        },
        input_name: {
          type: "string",
          description: "The input socket identifier or name on the modifier.",
        },
        value: {
          oneOf: [
            { type: "number" },
            { type: "boolean" },
            { type: "array" },
          ],
          description:
            "Value to assign to the modifier input (number, boolean, or array). " +
            "IMPORTANT: Booleans must be JSON true/false, NOT strings. Arrays must be JSON arrays of numbers. " +
            "Example (number): 2.5. Example (boolean): true. Example (array): [1.0, 0.0, 0.0].",
        },
      },
      required: ["object_name", "modifier_name", "input_name", "value"],
    },
    handler: async (args) => {
      const result = await sendToBlender("node/geonodes-set-input", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_node_tree_info",
    description:
      "Return detailed information about a node tree. " +
      "Reports node count, link count, a list of all nodes (name, type, location), " +
      "and a list of all links (from_node, from_socket, to_node, to_socket). " +
      "Useful for inspecting an existing material, geometry nodes setup, or compositor graph " +
      "before making further modifications. " +
      "tree_owner uses the same convention as blender_node_list. " +
      "Example call: { \"tree_owner\": \"MyMaterial\" }.",
    inputSchema: {
      type: "object",
      properties: {
        tree_owner: {
          type: "string",
          description:
            "Identifies the node tree: material name, 'COMPOSITING', " +
            "'object:ObjectName', or a node_group name.",
        },
      },
      required: ["tree_owner"],
    },
    handler: async (args) => {
      const result = await sendToBlender("node/tree-info", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_node_colorramp_set",
    description:
      "Configure the color stops of a ColorRamp node in a material's shader node tree. " +
      "material_name identifies the material, node_name is the exact name of the ColorRamp node " +
      "(must be of type ShaderNodeValToRGB / VALTORGB). " +
      "stops is an array of objects each with a 'position' (0.0–1.0) and a 'color' [r, g, b, a]. " +
      "All existing stops are replaced with the provided ones. " +
      "Returns the list of configured stops. " +
      "Example call: { \"material_name\": \"MyMaterial\", \"node_name\": \"ColorRamp\", \"stops\": [{ \"position\": 0.0, \"color\": [0, 0, 0, 1] }, { \"position\": 1.0, \"color\": [1, 1, 1, 1] }] }.",
    inputSchema: {
      type: "object",
      properties: {
        material_name: {
          type: "string",
          description: "Name of the material containing the ColorRamp node.",
        },
        node_name: {
          type: "string",
          description: "Exact name of the ColorRamp node to configure.",
        },
        stops: {
          type: "array",
          items: {
            type: "object",
            properties: {
              position: {
                type: "number",
                minimum: 0,
                maximum: 1,
                description: "Position of the color stop along the ramp (0.0 to 1.0).",
              },
              color: {
                type: "array",
                items: { type: "number" },
                minItems: 4,
                maxItems: 4,
                description: "RGBA color for this stop as [r, g, b, a].",
              },
            },
            required: ["position", "color"],
          },
          description:
            "Array of color stop definitions to apply to the ColorRamp. " +
            "IMPORTANT: Must be a JSON array of objects, NOT a string. " +
            "Example: [{ \"position\": 0.0, \"color\": [0, 0, 0, 1] }, { \"position\": 1.0, \"color\": [1, 1, 1, 1] }].",
        },
      },
      required: ["material_name", "node_name", "stops"],
    },
    handler: async (args) => {
      const result = await sendToBlender("node/colorramp-set", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_node_arrange",
    description:
      "Auto-arrange all nodes in a node tree into a readable left-to-right layout. " +
      "The algorithm performs a breadth-first traversal from the output node, " +
      "assigns each node a column depth, and positions nodes in a grid " +
      "with 250 px horizontal spacing and 100 px vertical spacing between rows. " +
      "This does not change any connections — only the visual positions of nodes are updated. " +
      "tree_owner uses the same convention as blender_node_list. " +
      "Returns the number of nodes repositioned. " +
      "Example call: { \"tree_owner\": \"MyMaterial\" }.",
    inputSchema: {
      type: "object",
      properties: {
        tree_owner: {
          type: "string",
          description:
            "Identifies the node tree: material name, 'COMPOSITING', " +
            "'object:ObjectName', or a node_group name.",
        },
      },
      required: ["tree_owner"],
    },
    handler: async (args) => {
      const result = await sendToBlender("node/arrange", args);
      return JSON.stringify(result, null, 2);
    },
  },
];
