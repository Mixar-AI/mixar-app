# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A failed generation says what failed, why (in the provider's words) and
what to do — from the job-queue client view through to every surface."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.common.api.exceptions import (
    InsufficientCreditsError,
    ServerError,
    ValidationError,
)
from mixar.modules.common.api.response import APIResponse
from mixar.modules.common.api.services.job_queue_service import JobQueueService
from mixar.modules.common.job_queue.core import failure_info as FI
from mixar.modules.common.job_queue.core.job import Job, JobState


def _normalized(data):
    response = APIResponse(
        success=True, status_code=200,
        data={"status": "success", "message": "ok", "data": data},
    )
    return JobQueueService._normalize_response(response)


FAILED_VIEW = {
    "job_id": "j1",
    "state": "failed",
    "error": "The generation was rejected by the provider's content policy.",
    "error_class": "content_policy",
    "error_reason": "fal submit failed (422): Prompt flagged: public figure",
    "vendor_code": "content_policy_violation",
}


def test_normalizer_keeps_backend_sentence_and_failure_fields():
    inner = _normalized(FAILED_VIEW).data["data"]
    # The backend's class sentence, not a fixed "Generation failed".
    assert inner["user_message"] == FAILED_VIEW["error"]
    assert inner["error_class"] == "content_policy"
    assert inner["error_reason"] == FAILED_VIEW["error_reason"]
    assert inner["vendor_code"] == "content_policy_violation"


def test_normalizer_tolerates_older_backend_without_fields():
    inner = _normalized({"job_id": "j1", "state": "failed"}).data["data"]
    assert inner["user_message"] == "Generation failed — please try again"
    assert inner["error_class"] is None


def test_standard_poll_records_reason_and_class():
    job = Job(label="Image")
    status, _ = job._parse_standard_poll(_normalized(FAILED_VIEW))
    assert status == "FAIL"
    assert job.error_class == "content_policy"
    assert FI.failure_headline(job) == "Blocked by content policy"
    assert FI.failure_message(job) == FAILED_VIEW["error"]
    assert FI.failure_reason(job) == FAILED_VIEW["error_reason"]
    details = FI.failure_details(job)
    assert "Reason: fal submit failed (422): Prompt flagged" in details
    assert "Change the prompt" in details
    assert "provider code content_policy_violation" in details


def test_reason_equal_to_message_is_not_repeated():
    job = Job(user_message="CUDA out of memory", error_reason="CUDA out of memory")
    assert FI.failure_reason(job) == ""


def test_submit_validation_error_shows_backend_detail():
    job = Job()
    error = ValidationError(
        "Model flux accepts at most 4 reference images", status_code=422,
    )
    FI.apply_client_failure(job, error, stage="submit")
    assert job.error_class == "invalid_input"
    assert job.user_message == "Model flux accepts at most 4 reference images"


def test_submit_credit_error_keeps_friendly_sentence():
    job = Job()
    FI.apply_client_failure(
        job, InsufficientCreditsError("Insufficient credits: need 12", status_code=402),
        stage="submit",
    )
    assert job.error_class == "credits"
    assert "out of credits" in job.user_message.lower()
    assert FI.failure_reason(job) == "Insufficient credits: need 12"
    assert "refunded" not in FI.failure_hint(job)


def test_server_error_detail_is_redacted():
    job = Job()
    FI.apply_client_failure(
        job,
        ServerError(
            "upload to https://bucket.s3.amazonaws.com/u/1/x.png?X-Amz-Signature=abc "
            "failed with api_key=sk-abcdefghijklmn",
            status_code=502,
        ),
        stage="submit",
    )
    assert "X-Amz-Signature" not in job.error_reason
    assert "sk-abcdefghijklmn" not in job.error_reason
    assert "https://bucket.s3.amazonaws.com/…" in job.error_reason


def test_client_timeout_does_not_claim_a_refund():
    job = Job(state=JobState.FAILED, error_class="timeout",
              user_message="Generation timed out — please try again")
    assert "refunded" not in FI.failure_hint(job)
    job.error_class = "vendor_down"
    assert "refunded" in FI.failure_hint(job)
