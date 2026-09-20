# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pinned catalogs + policy constants for local model support.

Everything the runtime layer trusts is pinned here at curation time:

- The llama.cpp runtime is pinned to one release tag. Every asset we may
  download carries its exact byte size and SHA-256 (computed from the
  released bytes on 2026-08-18; GitHub's releases API exposes the same
  values as ``assets[].digest``). A download that does not hash to the
  pinned value is discarded.
- Models are pinned to exact files in un-gated Hugging Face repos, with
  size + SHA-256 taken from the HF tree API (``lfs.oid`` is the LFS
  object's SHA-256) on the same date.

Nothing in this file imports bpy and nothing performs I/O.
"""

LOG_PREFIX = "[LocalModels]"

# ---------------------------------------------------------------------------
# llama.cpp runtime (pinned release)
# ---------------------------------------------------------------------------

LLAMA_CPP_TAG = "b10485"

RUNTIME_DOWNLOAD_URL_TEMPLATE = (
    "https://github.com/ggml-org/llama.cpp/releases/download/{tag}/{asset}"
)

# (os_key, arch_key) -> ordered candidate runtime builds. First entry is
# preferred (GPU-accelerated where a portable option exists); later entries
# are fallbacks for machines where the preferred build fails to start
# (e.g. no Vulkan driver). ``variant`` doubles as the install directory
# name under runtime_dir(); ``asset`` is the exact release asset filename.
#
# All sha256/size values were computed locally from the b10485 release
# assets on 2026-08-18.
RUNTIME_ASSETS = {
    ("mac", "arm64"): (
        {
            "variant": "macos-arm64",
            "asset": "llama-b10485-bin-macos-arm64.tar.gz",
            "sha256": "5a575b25e43f7ae8a5ccbc77e7dfa8d58ba3210367bb01d9b2a18ed82bdbeb3f",
            "size": 11086995,
        },
    ),
    ("mac", "x64"): (
        {
            "variant": "macos-x64",
            "asset": "llama-b10485-bin-macos-x64.tar.gz",
            "sha256": "849c1757150425afa1a2635c522815cc156d50a2e7aee588f078b267535289de",
            "size": 11392920,
        },
    ),
    ("windows", "x64"): (
        {
            "variant": "win-vulkan-x64",
            "asset": "llama-b10485-bin-win-vulkan-x64.zip",
            "sha256": "58b8134245fabc5f1cfd3cd1d8124485f94b20d97d79f81aee76bebace18f800",
            "size": 34820123,
        },
        {
            "variant": "win-cpu-x64",
            "asset": "llama-b10485-bin-win-cpu-x64.zip",
            "sha256": "9901fd2183d94523d12a2939b5f4aa97a55b2984d05d270439101ca33c3ea169",
            "size": 18475114,
        },
    ),
    ("windows", "arm64"): (
        {
            "variant": "win-cpu-arm64",
            "asset": "llama-b10485-bin-win-cpu-arm64.zip",
            "sha256": "d5e4b8183410275b9609575d89a2acb10b8f209ffdc2140b9e6a5773d6b04294",
            "size": 12233409,
        },
    ),
    ("linux", "x64"): (
        {
            "variant": "ubuntu-vulkan-x64",
            "asset": "llama-b10485-bin-ubuntu-vulkan-x64.tar.gz",
            "sha256": "27f1f868324014f0c0008b5644a377adfcf28df6995ae546a74cb653883085d9",
            "size": 33272494,
        },
        {
            "variant": "ubuntu-x64",
            "asset": "llama-b10485-bin-ubuntu-x64.tar.gz",
            "sha256": "fa5df4b36ebfbe24f914efcb3ca2a848932f512ee3ba3138b30b20d47cdd2e9a",
            "size": 16663446,
        },
    ),
    ("linux", "arm64"): (
        {
            "variant": "ubuntu-arm64",
            "asset": "llama-b10485-bin-ubuntu-arm64.tar.gz",
            "sha256": "2c2cab689c3c738b44d48abd5465d3dcf6d6815cc002fbe39c55b9cc1c980c82",
            "size": 13527557,
        },
    ),
}

# ---------------------------------------------------------------------------
# Model catalog (pinned GGUF files)
# ---------------------------------------------------------------------------

MODEL_DOWNLOAD_URL_TEMPLATE = (
    "https://huggingface.co/{repo}/resolve/main/{file}?download=true"
)

# Each entry: one main GGUF and (for vision models) one mmproj GGUF, both
# pinned by exact size + LFS SHA-256 from the HF tree API (2026-08-18).
# ``min_ram_gb`` is the vendor-guide working-set estimate, used only for
# UI hints; the actual fit rule lives in core/catalog.py.
MODEL_CATALOG = (
    {
        "id": "qwen3.5-2b",
        "label": "Qwen3.5 2B",
        "description": "Smallest vision-capable model — fast on any machine, good tool use.",
        "repo": "unsloth/Qwen3.5-2B-GGUF",
        "file": {
            "name": "Qwen3.5-2B-Q4_K_M.gguf",
            "size": 1280835840,
            "sha256": "aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223",
        },
        "mmproj": {
            "name": "mmproj-F16.gguf",
            "size": 668227264,
            "sha256": "7035e9cb8d7c6a9681d07eef9a364783e86ea4cd73faab2eabb4f43a101830c7",
        },
        "vision": True,
        "min_ram_gb": 3.5,
        "tool_call_quality": "good",
        "is_default": False,
    },
    {
        "id": "qwen3.5-4b",
        "label": "Qwen3.5 4B",
        "description": "Recommended default — balanced speed/quality, vision + very good tool use.",
        "repo": "unsloth/Qwen3.5-4B-GGUF",
        "file": {
            "name": "Qwen3.5-4B-Q4_K_M.gguf",
            "size": 2740937888,
            "sha256": "00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4",
        },
        "mmproj": {
            "name": "mmproj-F16.gguf",
            "size": 672423616,
            "sha256": "cd88edcf8d031894960bb0c9c5b9b7e1fea6ebee02b9f7ce925a00d12891f864",
        },
        "vision": True,
        "min_ram_gb": 5.5,
        "tool_call_quality": "very good",
        "is_default": True,
    },
    {
        "id": "qwen3.5-9b",
        "label": "Qwen3.5 9B",
        "description": "High-quality vision model for 16 GB machines — excellent tool use.",
        "repo": "unsloth/Qwen3.5-9B-GGUF",
        "file": {
            "name": "Qwen3.5-9B-Q4_K_M.gguf",
            "size": 5680522464,
            "sha256": "03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8",
        },
        "mmproj": {
            "name": "mmproj-F16.gguf",
            "size": 918166080,
            "sha256": "f70dc3509053962b0d0d3ee8a7eacebf5d60aa560cad78254ae8698516ae029f",
        },
        "vision": True,
        "min_ram_gb": 8.0,
        "tool_call_quality": "excellent",
        "is_default": False,
    },
    {
        "id": "gpt-oss-20b",
        "label": "GPT-OSS 20B",
        "description": "Text-only reasoning/agentic model (no image understanding).",
        "repo": "ggml-org/gpt-oss-20b-GGUF",
        "file": {
            "name": "gpt-oss-20b-MXFP4.gguf",
            "size": 12109566624,
            "sha256": "27cd6c432c7672cb812a92f611cf3ba7bbc35928262bb1e1253ff4ee6ae35901",
        },
        "mmproj": None,
        "vision": False,
        "min_ram_gb": 14.0,
        "tool_call_quality": "excellent (harmony format; text-only)",
        "is_default": False,
    },
    {
        "id": "qwen3.6-27b",
        "label": "Qwen3.6 27B",
        "description": "Agentic-coding flagship for 32 GB machines — vision + best tool use.",
        "repo": "unsloth/Qwen3.6-27B-GGUF",
        "file": {
            "name": "Qwen3.6-27B-Q4_K_M.gguf",
            "size": 16817244384,
            "sha256": "5ed60d0af4650a854b1755bd392f9aef4872643dc25a254bc68043fa638392a0",
        },
        "mmproj": {
            "name": "mmproj-F16.gguf",
            "size": 927607360,
            "sha256": "eacf610d1ee4bd5ed0197a0777dd8f4fceb8eefa27009067c7d496cb68fbde45",
        },
        "vision": True,
        "min_ram_gb": 17.0,
        "tool_call_quality": "excellent (agentic-coding flagship)",
        "is_default": False,
    },
)

DEFAULT_MODEL_ID = "qwen3.5-4b"

# ---------------------------------------------------------------------------
# Server / relay policy
# ---------------------------------------------------------------------------

DEFAULT_CTX_SIZE = 16384

# Managed llama-server listens on 127.0.0.1 at a port from this inclusive
# range; the chosen port persists in the manifest and is reused while free.
PORT_RANGE = (11500, 11599)

# First /health 200 after a cold start of a big model can take minutes
# (weights are read from disk into RAM).
HEALTH_TIMEOUT_S = 240

# One relayed llm.request round trip (local generation can be slow).
RELAY_TIMEOUT_S = 270.0

# Must mirror the backend's caps, and both sit well under the backend's
# 16 MiB WebSocket frame limit (uvicorn ws_max_size) — an oversized
# JSON-RPC frame kills the whole agent connection, not just one request.
MAX_RELAY_REQUEST_BYTES = 8 * 1024 * 1024
MAX_RELAY_RESPONSE_BYTES = 8 * 1024 * 1024

# Header allowlists for the relay — anything else is dropped, both ways.
RELAY_ALLOWED_REQUEST_HEADERS = frozenset({"accept", "authorization", "content-type"})
RELAY_ALLOWED_RESPONSE_HEADERS = frozenset(
    {"content-type", "openai-processing-ms", "retry-after", "x-request-id"}
)

# The only path the relay will ever hit on an approved base.
RELAY_CHAT_COMPLETIONS_PATH = "/v1/chat/completions"

# ---------------------------------------------------------------------------
# Download policy (see core/download.py)
# ---------------------------------------------------------------------------

DOWNLOAD_CHUNK_BYTES = 65536
DOWNLOAD_SOCKET_TIMEOUT_S = 120.0
DOWNLOAD_MAX_ATTEMPTS = 3
DOWNLOAD_RETRY_BACKOFF_S = 2.0
DOWNLOAD_RETRY_BACKOFF_FACTOR = 2.0
DOWNLOAD_PROGRESS_INTERVAL_S = 0.25

# Default total deadline: at least this many seconds, scaled up so a slow
# (200 KiB/s) link can still finish a multi-GB GGUF within budget.
DOWNLOAD_MIN_DEADLINE_S = 900
DOWNLOAD_DEADLINE_BYTES_PER_S = 200 * 1024

# ---------------------------------------------------------------------------
# Storage / UI identifiers
# ---------------------------------------------------------------------------

# Subpath under bpy.utils.user_resource("DATAFILES") (see core/paths.py).
DATAFILES_SUBDIR = "mixar/local_models"

MANIFEST_FILENAME = "manifest.json"

# Stable toast id for the sticky download/server-state toast (Stage 2).
LOCAL_MODEL_TOAST_ID = "mixar-local-model"

# llama-server child stdout/stderr land here (tempdir-relative filename).
SERVER_LOG_FILENAME = "mixar_llama_server.log"

# ---------------------------------------------------------------------------
# Detection of user-run local OpenAI-compatible servers
# ---------------------------------------------------------------------------

# (kind, default port) — probed via GET /v1/models on 127.0.0.1.
KNOWN_LOCAL_SERVERS = (
    ("ollama", 11434),
    ("lm_studio", 1234),
    ("omlx", 8000),
    ("llama_cpp", 8080),
)
