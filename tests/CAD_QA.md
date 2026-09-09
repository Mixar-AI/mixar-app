## CAD cleanup sub-agent

CAD implementation lives in `mixar-backend/modules/agent/agents/subagents/cad_cleanup/`:
the BaseAgent implementation, name classifier, stage helpers, reference taxonomy,
assembly/evidence checks, Gemini identification and metadata transport. The existing
agent registry and decorated tool-domain entry points remain in their normal locations.
The system prompt stays at `modules/agent/prompts/lanes/cad_cleanup.md` so the standard
prompt loader and admin overrides continue to work.

There is no separate CAD policy framework or delivery authorization token. CAD tools
call ordinary helper functions; final verify/save call the existing delivery checks
directly. The LLM chooses stages, evaluates evidence and decides what to investigate
next. Keep exact reference collection names, one Review collection and a separate
retained hidden-internals collection. Reuse evidence and inspect scoped candidates;
verify at major stage boundaries and final delivery, not after each small edit.

The client owns Blender operations: indexing, rendering/object IDs, rays, reversible
scene edits, collection membership, geometry integrity and local output files. Its
metadata bridge transfers bounded data and rejects stale targets; it neither selects
workflow steps nor issues approvals. Local paths, mesh buffers and recovery journals
do not travel to the backend or the LLM. Delivery compares the scene/assignment
revision used by the tool before writing. Transport version 2 needs a coordinated
backend deployment and client rebuild.

Validation lives in backend `tests/agent/cad_cleanup` and client
`tests/cad_cleanup_transport_qa.py`. Backend runtime tests run in CI, not locally.
Full-car acceptance still requires resolving the Run09 reopen/fingerprint/native
crash; do not bypass its integrity guard or claim synthetic tests prove car quality.
