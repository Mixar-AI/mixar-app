// Advanced physics tools — cloth, rigid body, soft body, fluid, collision, baking

import { sendToBlender } from "../../blender-bridge.js";

export const physicsTools = [
  {
    name: "blender_physics_cloth_add",
    description:
      "Add a Cloth physics modifier to a mesh object, enabling fabric simulation. " +
      "Optionally apply a material preset (COTTON, SILK, LEATHER, DENIM, RUBBER) that configures " +
      "realistic stiffness, mass, and quality settings for that material type. " +
      "Example call: { \"object_name\": \"Plane\", \"preset\": \"SILK\" }. " +
      "The object must be a mesh. After adding, the cloth will simulate on playback.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the mesh object to add cloth physics to.",
        },
        preset: {
          type: "string",
          enum: ["COTTON", "SILK", "LEATHER", "DENIM", "RUBBER"],
          description:
            "Optional cloth material preset. Must be UPPERCASE. " +
            "COTTON: medium stiffness, light. " +
            "SILK: very soft, light, drapes fluidly. " +
            "LEATHER: stiff, heavy. " +
            "DENIM: medium-stiff, medium weight. " +
            "RUBBER: elastic, heavy.",
        },
      },
      required: ["object_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("physics/cloth-add", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_physics_cloth_configure",
    description:
      "Configure parameters of an existing Cloth modifier on a mesh object. " +
      "Pass a params object with any combination of: mass (kg), tension_stiffness, " +
      "compression_stiffness, bending_stiffness, quality (simulation steps per frame), " +
      "air_damping, velocity_max. Only the keys provided will be updated. " +
      "Example call: { \"object_name\": \"Plane\", \"params\": { \"mass\": 0.3, \"tension_stiffness\": 15 } }.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the mesh object with a Cloth modifier.",
        },
        params: {
          type: "object",
          description:
            "IMPORTANT: Must be a JSON object, NOT a string. " +
            "Cloth settings to apply. Supported keys: " +
            "mass (float, kg), " +
            "tension_stiffness (float), " +
            "compression_stiffness (float), " +
            "bending_stiffness (float), " +
            "quality (int, simulation steps/frame), " +
            "air_damping (float), " +
            "velocity_max (float).",
          properties: {
            mass: { type: "number", description: "Cloth mass in kg." },
            tension_stiffness: {
              type: "number",
              description: "Resistance to stretching.",
            },
            compression_stiffness: {
              type: "number",
              description: "Resistance to compression.",
            },
            bending_stiffness: {
              type: "number",
              description: "Resistance to bending.",
            },
            quality: {
              type: "integer",
              description: "Simulation steps per frame (higher = more accurate).",
            },
            air_damping: {
              type: "number",
              description: "Air resistance / drag coefficient.",
            },
            velocity_max: {
              type: "number",
              description: "Maximum velocity clamping.",
            },
          },
        },
      },
      required: ["object_name", "params"],
    },
    handler: async (args) => {
      const result = await sendToBlender("physics/cloth-configure", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_physics_cloth_pin",
    description:
      "Assign a vertex group as the cloth pin group, fixing those vertices in space " +
      "so they do not move during simulation. The vertex group must already exist on the object. " +
      "Useful for hanging fabric from a fixed attachment point.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the mesh object with a Cloth modifier.",
        },
        vertex_group: {
          type: "string",
          description:
            "Name of the vertex group to use as the pin group. " +
            "Vertices in this group will be held in place during simulation.",
        },
      },
      required: ["object_name", "vertex_group"],
    },
    handler: async (args) => {
      const result = await sendToBlender("physics/cloth-pin", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_physics_rigid_body_add",
    description:
      "Add a Rigid Body physics simulation to an object. " +
      "ACTIVE objects are fully simulated (they move, fall, collide). " +
      "PASSIVE objects are immovable collision obstacles (e.g. floor, walls). " +
      "Optionally set the collision shape and mass.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the object to add rigid body physics to.",
        },
        type: {
          type: "string",
          enum: ["ACTIVE", "PASSIVE"],
          description:
            "Must be UPPERCASE. ACTIVE: object is simulated and moves freely. " +
            "PASSIVE: object is a static collision obstacle.",
        },
        shape: {
          type: "string",
          enum: [
            "BOX",
            "SPHERE",
            "CAPSULE",
            "CYLINDER",
            "CONE",
            "CONVEX_HULL",
            "MESH",
          ],
          description:
            "Collision shape. Must be UPPERCASE. BOX/SPHERE/CAPSULE/CYLINDER/CONE are fast primitives. " +
            "CONVEX_HULL approximates the mesh shape. MESH is exact but slow.",
        },
        mass: {
          type: "number",
          description: "Mass in kg for ACTIVE objects. Defaults to 1.0.",
        },
      },
      required: ["object_name", "type"],
    },
    handler: async (args) => {
      const result = await sendToBlender("physics/rigid-body-add", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_physics_rigid_body_configure",
    description:
      "Configure parameters of an existing Rigid Body on an object. " +
      "Pass a params object with any combination of: mass, friction, restitution " +
      "(bounciness), linear_damping, angular_damping, collision_shape, kinematic " +
      "(animated), use_deactivation. Only provided keys are updated. " +
      "Example call: { \"object_name\": \"Cube\", \"params\": { \"mass\": 2.0, \"friction\": 0.5, \"kinematic\": false } }.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the object with a rigid body.",
        },
        params: {
          type: "object",
          description:
            "IMPORTANT: Must be a JSON object, NOT a string. " +
            "Rigid body parameters to apply. Supported keys: " +
            "mass (float, kg), " +
            "friction (float, 0-1), " +
            "restitution (float, 0-1, bounciness), " +
            "linear_damping (float, 0-1), " +
            "angular_damping (float, 0-1), " +
            "collision_shape (string: BOX/SPHERE/CAPSULE/CYLINDER/CONE/CONVEX_HULL/MESH), " +
            "kinematic (bool, treat as animated), " +
            "use_deactivation (bool).",
          properties: {
            mass: { type: "number", description: "Mass in kg." },
            friction: { type: "number", description: "Surface friction (0-1)." },
            restitution: {
              type: "number",
              description: "Bounciness / restitution (0-1).",
            },
            linear_damping: {
              type: "number",
              description: "Linear velocity damping (0-1).",
            },
            angular_damping: {
              type: "number",
              description: "Rotational velocity damping (0-1).",
            },
            collision_shape: {
              type: "string",
              description: "Collision shape type.",
            },
            kinematic: {
              type: "boolean",
              description:
                "If true, object is animated (not fully simulated). " +
                "IMPORTANT: Must be a JSON boolean (true or false), NOT a string.",
            },
            use_deactivation: {
              type: "boolean",
              description:
                "Allow the object to deactivate when at rest. " +
                "IMPORTANT: Must be a JSON boolean (true or false), NOT a string.",
            },
          },
        },
      },
      required: ["object_name", "params"],
    },
    handler: async (args) => {
      const result = await sendToBlender("physics/rigid-body-configure", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_physics_soft_body_add",
    description:
      "Add a Soft Body physics modifier to a mesh object, enabling elastic/jelly-like " +
      "deformation simulation. Optionally configure initial parameters such as mass, " +
      "goal_stiffness, goal_damping, and pull/push stiffness.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the mesh object to add soft body physics to.",
        },
        params: {
          type: "object",
          description:
            "IMPORTANT: Must be a JSON object, NOT a string. " +
            "Optional soft body settings. Supported keys: " +
            "mass (float, per-vertex mass), " +
            "goal_stiffness (float, 0-1, how strongly verts return to rest shape), " +
            "goal_damping (float, 0-1), " +
            "pull (float, edge pull stiffness), " +
            "push (float, edge push stiffness), " +
            "damping (float, edge damping), " +
            "bend (float, bending stiffness).",
          properties: {
            mass: { type: "number", description: "Per-vertex mass." },
            goal_stiffness: {
              type: "number",
              description: "Goal stiffness (0-1).",
            },
            goal_damping: {
              type: "number",
              description: "Goal damping (0-1).",
            },
            pull: { type: "number", description: "Edge pull stiffness." },
            push: { type: "number", description: "Edge push stiffness." },
            damping: { type: "number", description: "Edge damping." },
            bend: { type: "number", description: "Bending stiffness." },
          },
        },
      },
      required: ["object_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("physics/soft-body-add", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_physics_collision_add",
    description:
      "Add a Collision modifier to a mesh object, making it act as a collision " +
      "obstacle for cloth and soft body simulations. Optionally set the outer thickness " +
      "and friction coefficient.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the mesh object to add collision physics to.",
        },
        thickness: {
          type: "number",
          description:
            "Outer collision thickness in Blender units. " +
            "Controls how far from the surface cloth/soft bodies are repelled. Defaults to 0.025.",
        },
        friction: {
          type: "number",
          description:
            "Surface friction coefficient (0 = frictionless, 1 = very sticky). Defaults to 5.0.",
        },
      },
      required: ["object_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("physics/collision-add", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_physics_fluid_add",
    description:
      "Add a Fluid (Mantaflow) physics modifier to an object and set its role. " +
      "DOMAIN defines the simulation bounding box (one per scene). " +
      "FLOW is a fluid emitter (source or sink). " +
      "EFFECTOR creates obstacles or force fields within the simulation.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the object to add fluid physics to.",
        },
        type: {
          type: "string",
          enum: ["DOMAIN", "FLOW", "EFFECTOR"],
          description:
            "Fluid role. Must be UPPERCASE. " +
            "DOMAIN — defines the simulation volume (bounding box). Only one domain per scene. " +
            "FLOW — fluid emitter or drain. " +
            "EFFECTOR — obstacle or guide within the simulation.",
        },
      },
      required: ["object_name", "type"],
    },
    handler: async (args) => {
      const result = await sendToBlender("physics/fluid-add", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_physics_bake",
    description:
      "Bake physics simulations to the cache so they play back deterministically. " +
      "If object_name is provided, the scene is set up with that object active before baking. " +
      "If omitted, all physics simulations in the scene are baked. " +
      "Optionally override the scene's start and end frame for the bake range.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description:
            "Optional: name of the object to focus baking on. " +
            "If omitted, all simulations in the scene are baked.",
        },
        start_frame: {
          type: "integer",
          description:
            "Optional: first frame of the bake range. Overrides the scene's current frame_start.",
        },
        end_frame: {
          type: "integer",
          description:
            "Optional: last frame of the bake range. Overrides the scene's current frame_end.",
        },
      },
      required: [],
    },
    handler: async (args) => {
      const result = await sendToBlender("physics/bake", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_physics_free_bake",
    description:
      "Free (clear) cached physics bake data so simulations will be re-evaluated " +
      "on the next playback or bake. If object_name is provided, that object is made active " +
      "before freeing. If omitted, all bake caches in the scene are freed.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description:
            "Optional: name of the object whose bake cache to free. " +
            "If omitted, all simulation caches in the scene are freed.",
        },
      },
      required: [],
    },
    handler: async (args) => {
      const result = await sendToBlender("physics/free-bake", args);
      return JSON.stringify(result, null, 2);
    },
  },
];
