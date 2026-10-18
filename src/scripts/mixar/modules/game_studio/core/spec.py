# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""``mixar_game_spec_v1`` (contract §2): settings, nodes and validation.

The scene stores only the SETTINGS (title, template, rules, player,
camera, world, ui) as JSON in ``scene["mixar_game_spec"]``. ``nodes`` are
derived from object roles at build time, keyed by object name — the glTF
node name — so a rename never leaves a stale entry behind.
"""

from __future__ import annotations

import copy
import json
import re

from ..constants import (DEFAULT_TITLE, PLATFORMS, SCENE_FILE, SKIES, SLUG_MAX, SPEC_PROP,
                         SPEC_SCHEMA, TEMPLATES, TITLE_MAX, WIN_RULES)
from . import roles

DEFAULT_SETTINGS = {
    "title": DEFAULT_TITLE,
    "slug": "",
    "template": "third_person",
    "rules": {"win": "collect_all", "target_score": 0, "time_limit_s": 0, "lives": 3},
    "player": {"move_speed": 6.0, "jump_velocity": 5.5, "gravity_scale": 1.0},
    "camera": {"distance": 6.0, "height": 2.5},
    "world": {"sky": "procedural", "sun": True, "ambient": 0.6},
    "ui": {"show_score": True, "show_timer": True, "title_screen": True},
}
SECTIONS = ("rules", "player", "camera", "world", "ui")
# Numeric fields: (type, min, max).
_NUMBERS = {
    ("rules", "target_score"): (int, 0, 100000),
    ("rules", "time_limit_s"): (int, 0, 86400),
    ("rules", "lives"): (int, 0, 99),
    ("player", "move_speed"): (float, 0.1, 100.0),
    ("player", "jump_velocity"): (float, 0.0, 100.0),
    ("player", "gravity_scale"): (float, 0.0, 10.0),
    ("camera", "distance"): (float, 0.5, 100.0),
    ("camera", "height"): (float, -50.0, 100.0),
    ("world", "ambient"): (float, 0.0, 4.0),
}
_CHOICES = {("rules", "win"): WIN_RULES, ("world", "sky"): SKIES}
_FLAGS = {("world", "sun"), ("ui", "show_score"), ("ui", "show_timer"), ("ui", "title_screen")}


def slugify(title: str) -> str:
    """Store slug rules: lowercase letters, digits, single hyphens, >= 3 chars."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(title or "").lower()).strip("-")
    slug = slug[:SLUG_MAX].strip("-") or "game"
    return slug if len(slug) >= 3 else f"{slug}-game"


def load_settings(scene) -> dict:
    """The scene's settings merged over the defaults (junk ignored)."""
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    try:
        stored = json.loads(scene.get(SPEC_PROP) or "{}")
    except (ValueError, TypeError, AttributeError):
        stored = {}
    if isinstance(stored, dict):
        merged, _errors = merge_settings(settings, stored)
        settings = merged
    return settings


def save_settings(scene, settings: dict) -> None:
    """Main thread only."""
    scene[SPEC_PROP] = json.dumps(settings, sort_keys=True)


def _coerce(path, value):
    if path in _NUMBERS:
        kind, low, high = _NUMBERS[path]
        if isinstance(value, bool):
            raise ValueError(f"{'.'.join(path)} must be a number")
        number = kind(value)
        if not low <= number <= high:  # also rejects NaN
            raise ValueError(f"{'.'.join(path)} must be between {low} and {high}")
        return number
    if path in _CHOICES:
        value = str(value)
        if value not in _CHOICES[path]:
            raise ValueError(f"{'.'.join(path)} must be one of {', '.join(_CHOICES[path])}")
        return value
    if path in _FLAGS:
        if not isinstance(value, bool):
            raise ValueError(f"{'.'.join(path)} must be true or false")
        return value
    raise ValueError(f"unknown setting {'.'.join(path)}")


def merge_settings(base: dict, changes: dict) -> tuple[dict, list[str]]:
    """``base`` updated with every valid field of ``changes``; each invalid
    field is skipped with one error line."""
    merged, errors = copy.deepcopy(base), []
    for key, value in (changes or {}).items():
        if value is None:
            continue
        if key == "title":
            title = " ".join(str(value).split())[:TITLE_MAX]
            if title:
                merged["title"] = title
            else:
                errors.append("title must not be empty")
        elif key == "slug":
            merged["slug"] = slugify(value) if str(value).strip() else ""
        elif key == "template":
            if value in TEMPLATES:
                merged["template"] = value
            else:
                errors.append(f"template must be one of {', '.join(TEMPLATES)}")
        elif key in SECTIONS:
            if not isinstance(value, dict):
                errors.append(f"{key} must be an object")
                continue
            for field, field_value in value.items():
                try:
                    merged[key][field] = _coerce((key, field), field_value)
                except (TypeError, ValueError) as exc:
                    errors.append(str(exc) if isinstance(exc, ValueError) and str(exc)
                                  else f"{key}.{field} is invalid")
        else:
            errors.append(f"unknown setting {key}")
    return merged, errors


def build_nodes(objects) -> list[dict]:
    """``nodes`` for every object that reaches the game, in name order."""
    nodes = []
    for obj in objects:
        if roles.in_game(obj):
            nodes.append({"name": obj.name, "role": roles.effective_role(obj),
                          "params": roles.get_params(obj)})
    return nodes


def build_spec(settings: dict, nodes: list[dict], version: str = "") -> dict:
    spec = copy.deepcopy(settings)
    spec["slug"] = spec.get("slug") or slugify(spec.get("title"))
    spec.update({
        "schema": SPEC_SCHEMA,
        "nodes": list(nodes),
        "scene_file": SCENE_FILE,
        "up_axis": "Y",
        "generator": {"app": "Mixar", "version": str(version or "")},
    })
    ordered = {"schema": spec.pop("schema")}
    ordered.update(spec)
    return ordered


def validate_spec(spec: dict) -> tuple[list[str], list[str]]:
    """``(errors, warnings)``. Errors block a build; warnings travel along."""
    errors, warnings = [], []
    if spec.get("schema") != SPEC_SCHEMA:
        errors.append(f"schema must be {SPEC_SCHEMA}")
    if spec.get("template") not in TEMPLATES:
        errors.append("unknown template")
    nodes = spec.get("nodes") or []
    by_role = {}
    for node in nodes:
        by_role.setdefault(node.get("role"), []).append(node.get("name"))
    players = by_role.get("player", [])
    if not players:
        errors.append("no player: tag exactly one object with the 'player' role")
    elif len(players) > 1:
        errors.append(f"{len(players)} players ({', '.join(players[:4])}); exactly one is allowed")
    if len(by_role.get("spawn", [])) > 1:
        warnings.append("several spawn markers; the first one is used")
    rules = spec.get("rules") or {}
    win = rules.get("win")
    if win == "collect_all" and not by_role.get("collectible"):
        errors.append("win rule collect_all needs at least one collectible")
    elif win == "reach_goal" and not by_role.get("goal"):
        errors.append("win rule reach_goal needs a goal")
    elif win == "survive" and not rules.get("time_limit_s"):
        errors.append("win rule survive needs rules.time_limit_s > 0")
    elif win == "score":
        if not rules.get("target_score"):
            errors.append("win rule score needs rules.target_score > 0")
        if not by_role.get("collectible"):
            warnings.append("win rule score has no collectibles to score with")
    if not any(role in by_role for role in ("static", "prop")):
        warnings.append("no static geometry: the player has nothing to stand on")
    return errors, warnings


def validate_platforms(platforms) -> tuple[list[str], list[str]]:
    """``(platforms, errors)``; ``None`` means ``["web"]``."""
    if platforms is None:
        return ["web"], []
    if isinstance(platforms, str):
        platforms = [platforms]
    clean, errors = [], []
    for platform in platforms or ():
        platform = str(platform).lower()
        if platform not in PLATFORMS:
            errors.append(f"unknown platform {platform!r}; use {', '.join(PLATFORMS)}")
        elif platform not in clean:
            clean.append(platform)
    if not clean and not errors:
        errors.append("no platform given")
    return clean, errors


STORE_TEXT_LIMITS = {"tagline": 140, "description": 8000, "content_rating": 32}
# The store keeps 8 genres / 20 tags of up to 32 characters.
STORE_LIST_LIMIT, STORE_WORD_LIMIT = 8, 32
CONTENT_RATINGS = ("everyone", "teen", "mature", "unrated")
MIN_PRICE_CENTS = 100  # paid games start at $1.00 (paid acquire is 501 for now)


def normalize_store_page(page) -> tuple[dict, list[str]]:
    """The §4 store-page fields with defaults; bad fields are dropped with
    an error each. ``price_cents`` defaults to 0 (free)."""
    clean = {"tagline": "", "description": "", "genres": [], "tags": [],
             "price_cents": 0, "content_rating": "everyone"}
    errors = []
    if page is None:
        return clean, errors
    if not isinstance(page, dict):
        return clean, ["store_page must be an object"]
    for key, value in page.items():
        if key in STORE_TEXT_LIMITS:
            if value is None:
                continue
            text = str(value).strip()[:STORE_TEXT_LIMITS[key]]
            if key == "content_rating":
                if not text:
                    continue
                if text not in CONTENT_RATINGS:
                    errors.append(f"content_rating must be one of {', '.join(CONTENT_RATINGS)}")
                    continue
            clean[key] = text
        elif key in ("genres", "tags"):
            limit = STORE_LIST_LIMIT if key == "genres" else 20
            items = [value] if isinstance(value, str) else value
            if not isinstance(items, (list, tuple)):
                errors.append(f"{key} must be a list of words")
                continue
            words = []
            for item in items:
                word = " ".join(str(item).split())[:STORE_WORD_LIMIT].lower()
                if word and word not in words:
                    words.append(word)
            clean[key] = words[:limit]
        elif key == "price_cents":
            try:
                if isinstance(value, bool):
                    raise ValueError
                cents = int(value)
                if cents < 0 or 0 < cents < MIN_PRICE_CENTS:
                    raise ValueError
                clean[key] = cents
            except (TypeError, ValueError):
                errors.append("price_cents must be 0 (free) or at least 100")
        else:
            errors.append(f"unknown store_page field {key}")
    return clean, errors
