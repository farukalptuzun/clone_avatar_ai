"""Request/response and job payload schemas."""
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    PENDING = "pending"
    PREPARING = "preparing"
    TTS = "tts"
    VIDEO_GEN = "video_gen"
    QUALITY_CHECK = "quality_check"
    POSTPROCESS = "postprocess"
    UGC_PACK = "ugc_pack"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    QUALITY_FAILED = "quality_failed"


class GenerateVideoRequest(BaseModel):
    """POST /generate-video body."""

    text: str = Field(..., min_length=1, description="Script text for TTS and video")
    consent_given: bool = Field(..., description="User consent for clone/usage")
    idempotency_key: str | None = Field(None, description="Optional idempotency key")
    # photo and optional media are uploaded as multipart; see route


class GenerateVideoResponse(BaseModel):
    job_id: str
    status: JobStatus
    message: str = "Job enqueued"


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    progress: float = 0.0
    current_step: str | None = None
    error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ResultResponse(BaseModel):
    job_id: str
    status: JobStatus
    video_url: str | None = None
    expires_at: datetime | None = None
    error: str | None = None


# Internal job payload (passed to Celery chain)
class PipelineJobPayload(BaseModel):
    job_id: str
    # Paths (S3 keys or local paths after upload)
    photo_path: str
    driving_video_path: str | None = None
    product_image_path: str | None = None
    text: str = ""
    consent_record_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
