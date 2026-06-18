"""Layered, agent-readable scene graph for Mixar.

One shared node registry (built from a single scene walk) feeds multiple
pluggable relation layers. The spatial layer is implemented end-to-end here;
geometry/semantic layers plug in later behind the same RelationLayer contract.

Entry point for running inside Mixar: ../run_scene_graph.py
"""
