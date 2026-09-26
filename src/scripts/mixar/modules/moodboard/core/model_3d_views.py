# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Multi-View Inputs on the Generate to 3D Node

When the node's catalog model publishes ``supports_multi_view``, the node
gains one optional image socket per vendor angle (``view:left``,
``view:back`` ...) beside its frontal image input. The SOCKET names the
angle, so a connection needs no labelling step and two images can never
claim the same view.

Submission reuses the frozen ``POST /job-queue/jobs`` multi-view shape
(:mod:`turnaround_payload`): the frontal image is ``image_s3_key`` /
``image_bytes_b64`` and each connected angle is one ``multi_view_images``
entry. The catalog's own untyped ``multi_view_images`` group is replaced by
these sockets, because an entry without a ``view_type`` is refused by the
vendor.
"""

from typing import List, Tuple

from ..constants import TURNAROUND_VIEW_TYPES

VIEW_SOCKET_PREFIX = "view:"
_CATALOG_MULTI_VIEW_GROUP = "multi_view_images"
_VIEW_TYPES = tuple(view for view, _label, _desc in TURNAROUND_VIEW_TYPES)


def view_socket_id(view_type: str) -> str:
    return f"{VIEW_SOCKET_PREFIX}{view_type}"


def view_type_for_socket(socket_id: str) -> str:
    """The angle a ``view:<type>`` socket carries, or "" for any other socket."""
    socket_id = socket_id or ""
    if not socket_id.startswith(VIEW_SOCKET_PREFIX):
        return ""
    view_type = socket_id[len(VIEW_SOCKET_PREFIX):]
    return view_type if view_type in _VIEW_TYPES else ""


def apply_view_sockets(contract: dict, model: dict) -> None:
    """Swap the catalog's untyped multi-view group for per-angle sockets.

    Models without ``supports_multi_view`` get no view sockets at all, so the
    node keeps its single-image surface. Image limits are recounted from the
    sockets that exist, matching ``build_input_contract``.
    """
    sockets = [
        socket for socket in contract.get("sockets", [])
        if socket.get("group_id") != _CATALOG_MULTI_VIEW_GROUP
        and not str(socket.get("id", "")).startswith(VIEW_SOCKET_PREFIX)
    ]
    if (model or {}).get("supports_multi_view"):
        for view_type, label, _desc in TURNAROUND_VIEW_TYPES:
            socket_id = view_socket_id(view_type)
            sockets.append({
                "id": socket_id,
                "label": label,
                "accepted_types": ["IMAGE"],
                "required": False,
                "group_id": socket_id,
                "repeatable": False,
            })
    contract["sockets"] = sockets
    limits = contract.setdefault("limits", {})
    limits["IMAGE"] = sum(
        1 for socket in sockets if "IMAGE" in socket.get("accepted_types", ())
    )


def split_model_3d_inputs(scene, node) -> Tuple[object, List[tuple]]:
    """``(frontal_image, [(view_type, media_item), ...])`` from the connections.

    Exactly one still must reach the non-view input(s): it is the vendor's
    frontal image. View sockets must carry stills too — a video there is a
    connection the job cannot honour, so it is refused rather than dropped.
    """
    from .node_graph import input_media_links
    from .media_utils import is_still_item

    frontal = []
    views = []
    for link, item in input_media_links(scene, node):
        view_type = view_type_for_socket(link.to_socket)
        if not view_type:
            if is_still_item(item):
                frontal.append(item)
            continue
        if not is_still_item(item):
            raise ValueError(f"The {view_type.replace('_', ' ')} view input needs an image")
        views.append((view_type, item))
    if len(frontal) != 1:
        detail = "connect one image" if not frontal else "connect only one image"
        raise ValueError(
            f"Generate to 3D needs exactly one image connection ({detail}; "
            f"found {len(frontal)})"
        )
    order = {view: index for index, view in enumerate(_VIEW_TYPES)}
    views.sort(key=lambda pair: order[pair[0]])
    return frontal[0].image, views


def build_view_socket_payload(scene, image, views, service_key, model_slug):
    """Multi-view payload fragment for connected view sockets.

    Refuses (terminal ``ValueError``) instead of degrading: a model that
    cannot take views, or a frontal image that already owns a Multiple Views
    set on the board — sending either set alone would build the model from
    different views than the user connected.
    """
    from .turnaround_payload import main_fragment, view_entry
    from .turnaround_views import group_id_for_main_image, model_accepts_multi_view

    if not model_accepts_multi_view(service_key, model_slug):
        raise ValueError(
            f"'{model_slug}' cannot use view inputs. Pick a multi-view model "
            "or disconnect the view inputs."
        )
    if group_id_for_main_image(scene, image):
        raise ValueError(
            f"'{image.name}' also has a Multiple Views set. Clear that set or "
            "disconnect the node's view inputs."
        )
    payload = main_fragment(scene, image)
    payload["multi_view_images"] = [
        view_entry(item.image, view_type, getattr(item, "s3_key", ""))
        for view_type, item in views
    ]
    return payload, []
