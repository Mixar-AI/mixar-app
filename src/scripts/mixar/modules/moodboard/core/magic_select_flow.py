# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Upload-and-click choreography for Magic Select, free of ``bpy``.

The user's model is "click the tool, click an object". The source image has
to be uploaded to the segmentation service first, but that is an
implementation step, never a user step: a click that lands while the upload
is still in flight is KEPT and runs the moment the upload succeeds, so the
user waits once rather than being told to wait and then having clicks
silently swallowed. Only one point is ever queued; a newer click replaces it.

The operator owns Blender state (props, cursor, status line) and asks this
object what to do next; every transition returns an action string so the
choreography is unit-testable without a running app.

Actions:
    SEGMENT   run a segmentation request for ``self.point`` now
    UPLOAD    start (or restart, after a failure) the upload
    WAIT      nothing to do yet; the queued point runs when the upload lands
    IDLE      nothing pending
"""

from typing import Optional, Tuple

Point = Tuple[float, float]

SEGMENT = "SEGMENT"
UPLOAD = "UPLOAD"
WAIT = "WAIT"
IDLE = "IDLE"

STATUS_READY = "Magic Select: click an object in the image   |   Esc to exit"
STATUS_FINDING = "Finding object…"
STATUS_FOUND = "Object selected. Click another object, or press Esc to finish"


class MagicSelectFlow:
    """One tool activation: upload lifecycle plus a single queued click."""

    def __init__(self, upload_ready: bool = False):
        # 'idle' | 'uploading' | 'ready' | 'failed'
        self.upload = "ready" if upload_ready else "idle"
        self.segmenting = False
        self.point: Optional[Point] = None
        self.found_once = False
        # One re-upload per request, like Box and Lasso: a service that keeps
        # forgetting the image must surface as a failure, not an endless loop.
        self.retried_expiry = False

    # -- queries ---------------------------------------------------------

    @property
    def busy(self) -> bool:
        """True while the user is waiting on the service for something."""
        return self.segmenting or (self.point is not None and self.upload != "ready")

    @property
    def pending(self) -> bool:
        """What the ``magic_select_pending`` mirror reports: a click is in flight."""
        return self.segmenting or self.point is not None

    def status_text(self) -> str:
        if self.pending:
            return STATUS_FINDING
        return STATUS_FOUND if self.found_once else STATUS_READY

    # -- transitions -----------------------------------------------------

    def upload_started(self) -> None:
        self.upload = "uploading"

    def click(self, x: float, y: float) -> str:
        """A click on the image. Always accepted; latest point wins."""
        self.point = (x, y)
        if self.segmenting:
            return WAIT
        if self.upload == "ready":
            return SEGMENT
        if self.upload in ("idle", "failed"):
            self.upload = "uploading"
            return UPLOAD
        return WAIT

    def upload_done(self, success: bool) -> str:
        """The upload callback. Returns SEGMENT when a click was waiting."""
        if not success:
            self.upload = "failed"
            self.point = None
            # A failed re-upload ends this request; the next click's request
            # must get its own retry budget.
            self.retried_expiry = False
            return IDLE
        self.upload = "ready"
        if self.point is not None and not self.segmenting:
            return SEGMENT
        return IDLE

    def segment_started(self) -> Point:
        """Consume the queued point; the request for it is now in flight."""
        assert self.point is not None
        point, self.point = self.point, None
        self.segmenting = True
        return point

    def segment_done(self, success: bool) -> str:
        """The segmentation callback. Returns SEGMENT when a newer click waits."""
        self.segmenting = False
        self.retried_expiry = False
        if success:
            self.found_once = True
        if self.point is None:
            return IDLE
        if self.upload == "ready":
            return SEGMENT
        if self.upload in ("idle", "failed"):
            # Nothing is uploading (the last upload was given up on), so the
            # waiting click has to start one itself.
            self.upload = "uploading"
            return UPLOAD
        return WAIT

    def upload_expired(self, point: Point) -> str:
        """The service forgot the image mid-request: put the point back and
        re-upload once. A click that arrived meanwhile keeps precedence.

        A second expiry in a row for the same request gives up: the upload is
        marked failed, the point is dropped, and IDLE tells the operator to
        report the failure (``segment_done`` then restarts the upload if a
        newer click is waiting)."""
        self.segmenting = False
        if self.retried_expiry:
            self.retried_expiry = False
            self.upload = "failed"
            return IDLE
        self.retried_expiry = True
        if self.point is None:
            self.point = point
        self.upload = "uploading"
        return UPLOAD
