# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Constants for Scribble Marks — pointing at the scene instead of describing it.

The user arms mark mode, which FREEZES the viewport (a still is captured and
drawn over the region while navigation is blocked), draws one or more marks
over that frozen frame, and sends a prompt. Each mark is resolved on the
CLIENT — raycast into world space for the object, the covered faces, a world
bbox and a vertex group — because only the client has the depsgraph.

The 2D half of the payload deliberately speaks the backend localizer's own
convention (``u`` left→right, ``v`` bottom→top, normalized in a named view's
image), so ``modules/agent/sculpt/localize.py`` can return a user mark instead
of asking a vision model to guess one.
"""

# =============================================================================
# PAYLOAD CONTRACT
# =============================================================================

#: Bumped only for a breaking change to the mark payload shape. The backend
#: refuses a version it does not know rather than misreading fields.
MARK_PAYLOAD_VERSION = 1

#: The surface a mark was made on. Only the 3D viewport is wired; the payload
#: carries the field so a second surface (marking a moodboard image) can be
#: added without changing the shape the backend already parses.
SURFACE_VIEW3D = "view3d"

#: How the ink of a whole freeze is read. POINT is marks that each mean
#: "this" or "here"; SKETCH is a DRAWING — a road with cars and trees on the
#: side — that the agent should read as a picture of what to build, laid out
#: where it was drawn. The reading is decided on the client (``core/sketch.py``),
#: shown in the hint pill, and overridable, because a drawing chopped into
#: per-pause "marks" arrives as nine placement targets and the agent builds
#: nine unrelated things at them. Advisory like the gesture labels: both
#: representations travel, the label says which one the user meant.
INTENT_POINT = "point"
INTENT_SKETCH = "sketch"

#: Gesture labels. Always advisory — the raw polygon travels alongside, so the
#: agent can disagree with a misclassification instead of being stuck with it.
GESTURE_POINT = "point"
GESTURE_CIRCLE = "circle"
GESTURE_ARROW = "arrow"
GESTURE_STRIKE = "strike"
GESTURE_STROKE = "stroke"

#: Why a mark resolved to nothing. Reported rather than silently dropped — an
#: agent that knows the user pointed at empty space can say so.
EMPTY_NO_HIT = "no_hit"
EMPTY_BACKGROUND = "background"
EMPTY_TOO_SMALL = "too_small"

#: A mark on empty space still lands SOMEWHERE: its rays are intersected with
#: the world ground plane (z = 0, Blender's grid floor) and reported as a
#: plane hit under this label — kept apart from a real surface hit so the
#: agent knows nothing is built there yet and treats it as a placement target.
PLANE_GROUND = "ground"
GROUND_PLANE_Z = 0.0

#: A ray that meets the ground plane farther than this from the eye (metres)
#: is treated as sky: a near-horizontal ray crosses z = 0 kilometres away, and
#: reporting that as "where they pointed" would send an object to the horizon.
GROUND_MAX_DISTANCE = 1000.0

# =============================================================================
# CAPTURE LIMITS
# =============================================================================

#: Draft marks a message may carry. Pointing needs a handful ("move THIS
#: over THERE" is two), but a SKETCH is chopped into one mark per pen-up
#: pause, and a road with a few cars and trees is easily fifteen of them —
#: at the old cap of 8 the second half of the drawing was silently refused.
MAX_MARKS_PER_TURN = 32

#: Strokes per mark. An arrow is 2 (shaft + head), an X is 2, a quickly drawn
#: car is 6 or 7. Reaching the cap COMMITS the group and starts a new one
#: rather than dropping ink — nothing the user drew is ever thrown away.
MAX_STROKES_PER_MARK = 16

#: Captured samples kept per stroke before decimation. Tablets emit far more
#: than this; the tail is dropped rather than growing the buffer.
MAX_POINTS_PER_STROKE = 512

#: Minimum on-screen distance between two captured samples, in unscaled
#: pixels (callers multiply by UI_SCALE_FAC). Decimates tablet input at the
#: source so the stroke store stays bounded on a high-DPI display.
MIN_SAMPLE_DIST_PX = 2.0

#: Pen-up idle after which the strokes drawn so far become ONE mark.
#: This is what groups an arrow's shaft and head, or an X's two lines, without
#: asking the user to declare it — the same idle-commit shape the chat
#: handwriting canvas uses (INK_IDLE_COMMIT_SEC in mixie_chat_ink_intern.hh),
#: so the gesture is one people meet twice inside one Scribble mode.
MARK_COMMIT_IDLE_S = 0.6

#: Modal timer period. Shorter than the idle above, so a commit fires at most
#: one period late.
MARK_TIMER_STEP_S = 0.15

# =============================================================================
# SERIALIZATION LIMITS
# =============================================================================

#: Points kept per serialized mark polygon. The agent needs a shape, not a
#: trace; 32 points describes any hand-drawn loop well past legibility.
MARK_POLYGON_MAX_POINTS = 32

#: Points kept per RAW stroke stored with a mark (normalized). These are what
#: the annotated frame is drawn from — the ink the user actually put down, not
#: its convex hull — so they are kept finer than the polygon: at 48 a car
#: still looks like a car.
MARK_STROKE_MAX_POINTS = 48

#: Samples per stroke projected into world space at commit time (raycast, or
#: the ground plane where the ray hits nothing). Eight is enough to say where
#: a road runs; the drawing itself is carried by the annotated frame.
STROKE_WORLD_POINTS = 8

#: Normalized coordinates are rounded to this many decimals — ~0.1 px on a
#: 1080p frame, and it keeps the JSON small enough to sit in a prompt.
UV_DECIMALS = 4

#: World-space coordinates in the payload, in metres.
WORLD_DECIMALS = 4

#: Hard cap on the serialized mark payload. Marks ride inside the model's
#: context, so this is a prompt-budget limit, not a transport one. Sized for
#: a sketch: thirty-odd ground marks plus the stroke block below.
MARK_JSON_MAX_BYTES = 40000

# =============================================================================
# SKETCH READING
# =============================================================================
# Deterministic, like the gesture reader, and for the same reason. Every
# threshold is a count or a ratio, so it holds at any DPI.

#: A freeze needs at least this many strokes to be a drawing at all. Three
#: circles on empty ground are three placement targets, not a sketch.
SKETCH_MIN_STROKES = 4

#: ...of which at least this many must be OPEN lines (not closed loops, not
#: taps). A layout of circled spots has none; a drawing of anything has many.
SKETCH_MIN_OPEN_STROKES = 3

#: At least this fraction of the freeze's marks must read as DRAWN — ink on
#: nothing, an irregular non-gesture line, or a three-plus-stroke doodle —
#: rather than as a pointing gesture on an object.
SKETCH_DRAWN_FRACTION = 0.5

#: A mark of this many strokes is a doodle: arrows are two, X's are two.
SKETCH_DOODLE_STROKES = 3

#: Sketching over an existing surface (a floor mesh) hits it with every
#: stroke. A circled figure covering less than this fraction of the object it
#: landed on, in a session of at least SKETCH_CANVAS_MIN_STROKES strokes, is
#: drawn ON the surface rather than selecting it.
SKETCH_MAX_OBJECT_FRACTION = 0.15
SKETCH_CANVAS_MIN_STROKES = 8

#: A stroke whose bbox diagonal is under this, normalized, is a tap
#: (~12 px on a 1080-tall frame, matching POINT_MAX_DIAG_PX).
SKETCH_TAP_MAX_UV = 0.012

#: Strokes carried in the payload's sketch block. The LONGEST are kept —
#: outlines and roads over the dots that detail them.
SKETCH_MAX_STROKES = 48

#: World points per stroke on the wire (thinned further under budget).
SKETCH_WORLD_POINTS = STROKE_WORLD_POINTS

#: Strokes named individually in the client prose before "and N more".
SKETCH_PROSE_STROKES = 12

# =============================================================================
# GESTURE CLASSIFICATION
# =============================================================================
# Deterministic and cheap, because asking a model what the squiggle meant is
# exactly the guessing this feature exists to remove. Every threshold below is
# scale-free (a ratio) except the point tests, which are genuinely about
# whether the hand moved at all.

#: A stroke whose total path length is under this (unscaled px) is a tap.
POINT_MAX_PATH_PX = 14.0

#: ...and whose bounding box diagonal is under this. Both must hold, so a
#: slow deliberate short drag still reads as a stroke.
POINT_MAX_DIAG_PX = 12.0

#: A stroke is closed when the gap between its endpoints is within this
#: fraction of its bbox diagonal. Deliberately looser than a drafting tool's:
#: circling something on screen routinely leaves a fifth of the diameter open,
#: and treating that as an open squiggle loses the user's actual meaning.
CLOSE_GAP_FACTOR = 0.25

#: A stroke also counts as closed when its total turning reaches this many
#: degrees — it went most of the way round something. This catches the spiral
#: that overshoots its start point and so fails the endpoint-gap test despite
#: obviously being a loop.
#:
#: Enclosed-area-vs-hull was tried here first and is WRONG: any convex open
#: arc encloses essentially all of its own hull once you join its endpoints,
#: so a 130-degree swipe read as a closed loop. Turning measures how far the
#: pen actually travelled around, which is the thing that makes a loop a loop.
CLOSE_TURN_DEG = 300.0

#: bbox_diagonal / path_length at or above this means the stroke is a straight
#: line — a strike-through rather than a squiggle. A perfect line is 1.0.
STRAIGHT_RATIO = 0.90

#: An arrow head stroke may be at most this fraction of the shaft's length.
ARROW_HEAD_MAX_RATIO = 0.45

#: ...and its centroid must sit within this fraction of the shaft's bbox
#: diagonal from one of the shaft's endpoints.
ARROW_HEAD_NEAR_FACTOR = 0.35

#: Single-stroke arrow: a direction change of at least this many degrees,
#: occurring inside the final ARROW_TURN_TAIL fraction of the path.
ARROW_TURN_DEG = 75.0
ARROW_TURN_TAIL = 0.3

#: The tangent used for an arrow's direction is measured over this fraction of
#: the shaft, so a wobbly final sample cannot swing the reported heading.
ARROW_TANGENT_SPAN = 0.25

# =============================================================================
# RESOLUTION (raycast tiers)
# =============================================================================

#: Tier 3 samples the mark's polygon on an N x N grid. 24 x 24 is at most 576
#: BVH raycasts — a few milliseconds — and resolves coverage finely enough to
#: tell "the roof" from "the house".
COVERAGE_GRID = 24

#: Objects reported per mark, ranked by covered area. Past a handful the list
#: is noise the model has to read every turn.
MAX_OBJECTS_PER_MARK = 6

#: An object holding less than this fraction of the mark's hits is dropped —
#: it is a sliver caught at the edge of the loop, not something pointed at.
MIN_OBJECT_COVERAGE = 0.04

#: Below this coverage of the object's own on-screen area, the mark is treated
#: as selecting PART of the object, and a vertex group is written.
PARTIAL_COVERAGE_MAX = 0.85

#: A mark covering fewer than this many hits is reported as too small to
#: resolve rather than being pinned to whatever single ray happened to land.
MIN_HITS_FOR_COVERAGE = 3

#: Rays are cast this far into the scene before giving up.
RAYCAST_DISTANCE = 1.0e6

#: A vertex group holding fewer than this many vertices is not written — it
#: would name a selection too sparse to edit, and an agent told to "select
#: this group" would then act on almost nothing.
MIN_MARKED_VERTICES = 3

#: Meshes above this vertex count skip the vertex-group pass. The projection
#: is vectorized and handles large meshes in milliseconds, but this runs while
#: the user waits for their message to send, so there is a ceiling. Above it
#: the mark still resolves to the object — only the sub-object selection is
#: skipped, and the reason is reported.
MAX_MESH_VERTICES_FOR_GROUP = 2_000_000

# =============================================================================
# SCENE ENTITIES
# =============================================================================
# A mark that lives only in one turn's context dies to context compaction, so
# every mark also lands in the .blend as a named, addressable noun.

#: Collection holding baked mark cameras. Hidden from render.
MARK_COLLECTION = "Mixar Marks"

#: Baked view camera, formatted with the mark's serial: mixar_mark_view_0001.
MARK_CAMERA_PREFIX = "mixar_mark_view_"

#: Vertex group written on the dominant object: mixar_mark_0001.
MARK_VERTEX_GROUP_PREFIX = "mixar_mark_"

#: Serial width for both names above.
MARK_SERIAL_DIGITS = 4

#: Frozen-frame stills, as bpy.data.images names.
FROZEN_IMAGE_NAME = "mixar_mark_frame"
ANNOTATED_IMAGE_NAME = "mixar_mark_frame_annotated"

# =============================================================================
# OVERLAY
# =============================================================================

#: Ink colour of a live mark (RGBA, linear). Cyan reads on both a bright clay
#: render and a dark material preview, which red and green do not.
MARK_INK_COLOR = (0.31, 0.85, 0.82, 1.0)

#: Ink of a mark already committed this turn — same hue, quieter.
MARK_INK_COLOR_SETTLED = (0.31, 0.85, 0.82, 0.55)

#: Stroke width in unscaled pixels.
MARK_INK_WIDTH = 3.0

#: Scrim laid over the frozen frame so it reads as paused, not merely idle.
MARK_SCRIM_COLOR = (0.02, 0.03, 0.04, 0.18)

#: Marks stay drawn while the freeze is up. Sending lowers the freeze, so the
#: ink comes off the viewport and the count on the toolbar toggle becomes the
#: badge — showing the marks while the agent works is reassuring, leaving the
#: whole frozen frame up forever is not.

#: Hint pill along the top of the frozen frame. Not decoration: a frozen
#: viewport with no legend is a viewport the user cannot work out how to leave,
#: and Esc is undiscoverable on its own.
MARK_HINT_HEIGHT_PX = 28.0
MARK_HINT_PAD_X_PX = 14.0
MARK_HINT_TOP_GAP_PX = 12.0
MARK_HINT_FONT_PX = 12
MARK_HINT_BG_COLOR = (0.05, 0.07, 0.09, 0.86)
MARK_HINT_TEXT_COLOR = (0.86, 0.93, 0.95, 1.0)
MARK_HINT_ACCENT_COLOR = (0.31, 0.85, 0.82, 1.0)

#: What the pill says. Both states name every control that exists, because a
#: mode whose boundaries and recovery are invisible is the failure the Thinkink
#: study (arXiv:2607.21468) found first: users could not tell which mode they
#: were in, and asked for visible controls and a way to undo.
MARK_HINT_IDLE = (
    "Draw here to point or sketch  ·  Write in the chat to type  ·  Esc when done"
)
#: ...and once ink is down, what the ink is being READ as, with the way to
#: change the reading. Both readings name Tab: a sketch mistaken for nine
#: marks is exactly the misread the user must be able to see and flip.
MARK_HINT_MARKED = (
    "{count} mark{plural}  ·  Tab: read as a sketch  ·  Backspace undoes the "
    "last  ·  Esc when done"
)
MARK_HINT_SKETCH = (
    "Sketch: {count} stroke{plural}, built as drawn  ·  Tab: read as marks  ·  "
    "Backspace undoes the last  ·  Esc when done"
)
