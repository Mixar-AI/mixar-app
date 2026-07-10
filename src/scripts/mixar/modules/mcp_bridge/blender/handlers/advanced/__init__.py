# Advanced handlers package.
# Importing each module triggers register_handler() calls at import time.

from . import export_extended       # noqa: F401 — registers export/obj, export/stl, export/usd, import/reference-image
from . import validation            # noqa: F401 — registers validation/mesh, validation/export-ready, validation/scene
from . import python_exec           # noqa: F401 — registers python/exec, python/exec-file

from . import modeling              # noqa: F401 — registers mesh/from-data, mesh/edit, mesh/select, mesh/separate, mesh/merge, mesh/normals
from . import uv                    # noqa: F401 — registers uv/unwrap, uv/pack-islands, uv/info
from . import analysis             # noqa: F401 — registers analysis/mesh, analysis/batch
from . import viewport             # noqa: F401 — registers viewport/screenshot, viewport/render-preview, viewport/graphics-capture
from . import reference_extended   # noqa: F401 — stub for reference extended
from . import sculpt               # noqa: F401 — registers sculpt/* routes
from . import armature             # noqa: F401 — registers armature/* routes
from . import animation_extended   # noqa: F401 — registers anim/* routes
from . import node                 # noqa: F401 — registers node/* routes
from . import curve                # noqa: F401 — registers curve/* routes
from . import light                # noqa: F401 — registers light/* routes
from . import camera               # noqa: F401 — registers camera/* routes
from . import texture              # noqa: F401 — registers texture/* routes
from . import particle             # noqa: F401 — registers particle/* routes
from . import physics              # noqa: F401 — registers physics/* routes
from . import constraint           # noqa: F401 — registers constraint/* routes
from . import render_extended      # noqa: F401 — registers render/* extended routes
from . import grease_pencil        # noqa: F401 — registers gp/* routes
from . import text                 # noqa: F401 — registers text/* routes
from . import lattice              # noqa: F401 — registers lattice/* routes
from . import vertex_group         # noqa: F401 — registers vgroup/* routes
from . import addon                # noqa: F401 — registers addon/* routes
from . import file_extended        # noqa: F401 — registers file/append, file/link
from . import scene_extended       # noqa: F401 — registers scene/cleanup
from . import object_extended      # noqa: F401 — registers object/rename, object/set-origin
from . import modifier_extended    # noqa: F401 — registers modifier/reorder
from . import material_extended    # noqa: F401 — registers material/edit, material/add-texture, material/remove
