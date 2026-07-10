// Advanced particle tools — particle systems, hair, emitter physics

import { sendToBlender } from "../../blender-bridge.js";

export const particleTools = [
  {
    name: "blender_particle_create",
    description:
      "Add a new particle system to an existing Blender object. " +
      "type must be 'EMITTER' (classical particle emitter) or 'HAIR' (strand-based hair). " +
      "An optional name sets both the particle system slot name and its settings data-block name. " +
      "Returns the new system name, its index on the object, and the particle type. " +
      "Note: In Blender 4.x, legacy particle systems are deprecated in favour of Geometry Nodes hair — " +
      "a warning is included in the response when running on Blender 4.x. " +
      "Example call: { \"object_name\": \"Sphere\", \"type\": \"EMITTER\", \"name\": \"Rain\" }.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the target object that will receive the particle system.",
        },
        type: {
          type: "string",
          enum: ["EMITTER", "HAIR"],
          description:
            "Particle system type. Must be UPPERCASE. EMITTER spawns particles from the surface; " +
            "HAIR generates strand geometry for fur or hair.",
        },
        name: {
          type: "string",
          description:
            "Optional name for the particle system slot and its settings data-block. " +
            "Defaults to Blender's auto-generated name (e.g. 'ParticleSystem').",
        },
      },
      required: ["object_name", "type"],
    },
    handler: async (args) => {
      const result = await sendToBlender("particle/create", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_particle_configure",
    description:
      "Apply a dictionary of settings to an existing particle system on an object. " +
      "Common configurable parameters include: " +
      "count (integer, total particle count), " +
      "frame_start / frame_end (float, emission frame range), " +
      "lifetime (float, particle lifetime in frames), " +
      "emit_from ('VERT', 'FACE', or 'VOLUME'), " +
      "physics_type ('NO', 'NEWTONIAN', 'KEYED', 'BOIDS', or 'FLUID'), " +
      "render_type ('HALO', 'LINE', 'PATH', 'OBJECT', or 'COLLECTION'). " +
      "Only the keys present in params are applied; all others are left unchanged. " +
      "Returns the object name, system name, and the params that were applied. " +
      "Example call: { \"object_name\": \"Sphere\", \"system_name\": \"Rain\", \"params\": { \"count\": 5000, \"lifetime\": 50 } }.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the object that owns the particle system.",
        },
        system_name: {
          type: "string",
          description: "Name of the particle system slot to configure.",
        },
        params: {
          type: "object",
          description:
            "Key/value pairs mapping directly to ParticleSettings attributes. " +
            "Supported keys: count, frame_start, frame_end, lifetime, emit_from, " +
            "physics_type, render_type. Unknown keys are silently skipped.",
          additionalProperties: true,
        },
      },
      required: ["object_name", "system_name", "params"],
    },
    handler: async (args) => {
      const result = await sendToBlender("particle/configure", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_particle_hair_length",
    description:
      "Set the strand length on a HAIR particle system. " +
      "Corresponds to ParticleSettings.hair_length in Blender. " +
      "This only has a visible effect when the system type is HAIR. " +
      "Returns the object name, system name, and the new hair_length value. " +
      "Example call: { \"object_name\": \"Head\", \"system_name\": \"Hair\", \"length\": 0.3 }.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the object that owns the hair particle system.",
        },
        system_name: {
          type: "string",
          description: "Name of the HAIR particle system slot.",
        },
        length: {
          type: "number",
          description:
            "Desired hair strand length in Blender units. Must be a positive float (e.g. 0.5).",
        },
      },
      required: ["object_name", "system_name", "length"],
    },
    handler: async (args) => {
      const result = await sendToBlender("particle/hair-length", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_particle_hair_density",
    description:
      "Set the strand count (density) on a HAIR particle system. " +
      "Adjusts ParticleSettings.count, which controls how many hair strands are generated. " +
      "Higher counts produce denser hair but increase viewport and render cost. " +
      "Returns the object name, system name, and the new count value. " +
      "Example call: { \"object_name\": \"Head\", \"system_name\": \"Hair\", \"count\": 5000 }.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the object that owns the hair particle system.",
        },
        system_name: {
          type: "string",
          description: "Name of the HAIR particle system slot.",
        },
        count: {
          type: "integer",
          description:
            "Total number of hair strands to emit. Must be a positive integer (e.g. 1000).",
          minimum: 1,
        },
      },
      required: ["object_name", "system_name", "count"],
    },
    handler: async (args) => {
      const result = await sendToBlender("particle/hair-density", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_particle_emitter_physics",
    description:
      "Adjust physics parameters on an EMITTER particle system. " +
      "All three parameters are optional — only those provided are changed. " +
      "gravity controls the effector_weights.gravity multiplier (1.0 = full scene gravity, 0.0 = weightless). " +
      "velocity maps to the normal_factor, controlling initial outward speed from the emitter surface. " +
      "lifetime sets the number of frames each particle lives before dying. " +
      "Returns the object name, system name, and the values actually applied. " +
      "Example call: { \"object_name\": \"Emitter\", \"system_name\": \"Sparks\", \"gravity\": 0.5, \"velocity\": 3.0, \"lifetime\": 30 }.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the object that owns the emitter particle system.",
        },
        system_name: {
          type: "string",
          description: "Name of the EMITTER particle system slot.",
        },
        gravity: {
          type: "number",
          description:
            "Gravity influence multiplier (effector_weights.gravity). " +
            "0.0 = no gravity, 1.0 = full gravity, negative values invert gravity.",
        },
        velocity: {
          type: "number",
          description:
            "Initial emission velocity along the surface normal (normal_factor). " +
            "Positive values launch particles away from the surface.",
        },
        lifetime: {
          type: "number",
          description:
            "Number of frames each emitted particle lives before it is removed.",
          minimum: 1,
        },
      },
      required: ["object_name", "system_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("particle/emitter-physics", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_particle_instance_object",
    description:
      "Assign an instance object to a particle system so each particle renders as a copy of that object. " +
      "Sets render_type to 'OBJECT' and assigns the named object to ParticleSettings.instance_object. " +
      "Both the emitting object and the instance object must already exist in the scene. " +
      "Returns the object name, system name, and the resolved instance object name. " +
      "Example call: { \"object_name\": \"Ground\", \"system_name\": \"Rocks\", \"instance_object\": \"Rock_01\" }.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the object that owns the particle system.",
        },
        system_name: {
          type: "string",
          description: "Name of the particle system slot.",
        },
        instance_object: {
          type: "string",
          description:
            "Name of the Blender object to render at each particle position. " +
            "This object must exist in bpy.data.objects.",
        },
      },
      required: ["object_name", "system_name", "instance_object"],
    },
    handler: async (args) => {
      const result = await sendToBlender("particle/instance-object", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_particle_weight_paint",
    description:
      "Bind a vertex group to the density channel of a particle system. " +
      "Sets ParticleSystem.vertex_group_density to the named vertex group, " +
      "causing particles to emit more densely where vertex weights are higher. " +
      "The vertex group must already exist on the object. " +
      "Pass an empty string to clear the density vertex group binding. " +
      "Returns the object name, system name, and the applied vertex group name. " +
      "Example call: { \"object_name\": \"Terrain\", \"system_name\": \"Grass\", \"vertex_group\": \"GrassDensity\" }.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the object that owns the particle system.",
        },
        system_name: {
          type: "string",
          description: "Name of the particle system slot.",
        },
        vertex_group: {
          type: "string",
          description:
            "Name of the vertex group to use for density weighting. " +
            "Pass an empty string ('') to clear the binding.",
        },
      },
      required: ["object_name", "system_name", "vertex_group"],
    },
    handler: async (args) => {
      const result = await sendToBlender("particle/weight-paint", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_particle_remove",
    description:
      "Remove a particle system slot from an object. " +
      "The system is looked up by name, made active, then deleted via bpy.ops.object.particle_system_remove(). " +
      "This operation is irreversible without an undo stack. " +
      "Returns the object name and the name of the system that was removed.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the object from which the particle system should be removed.",
        },
        system_name: {
          type: "string",
          description: "Name of the particle system slot to delete.",
        },
      },
      required: ["object_name", "system_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("particle/remove", args);
      return JSON.stringify(result, null, 2);
    },
  },
];
