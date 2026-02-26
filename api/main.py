"""FastAPI application entrypoint."""
from contextlib import asynccontextmanager
from uuid import uuid4

from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from shared.audit_log import audit_log
from shared.config import settings
from shared.job_store import job_store
from shared.schemas import (
    GenerateVideoResponse,
    JobStatus,
    JobStatusResponse,
    ResultResponse,
)
from shared.metrics import get_metrics, get_prometheus_text
from shared.storage import get_result_local_path
from workers.tasks import run_pipeline


def make_job_id() -> str:
    return str(uuid4())


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # shutdown cleanup if needed


app = FastAPI(title="Clone Avatar AI", version="0.1.0", lifespan=lifespan)


@app.post("/generate-video", response_model=GenerateVideoResponse)
async def generate_video(
    text: str = Form(..., min_length=1),
    consent_given: bool = Form(...),
    idempotency_key: str | None = Form(None),
    photo: UploadFile = File(...),
    driving_video: UploadFile | None = File(None),
    product_image: UploadFile | None = File(None),
):
    if not consent_given:
        raise HTTPException(status_code=400, detail="consent_given must be true")
    job_id = idempotency_key or make_job_id()
    if job_store.get(job_id):
        return GenerateVideoResponse(
            job_id=job_id,
            status=JobStatus.PENDING,
            message="Job already exists (idempotency)",
        )
    # Yüklenen dosyalar yerel storage'a yazılıyor (worker aynı path'ten okur)
    base = Path(settings.storage_base_path) / settings.inputs_prefix / job_id
    base.mkdir(parents=True, exist_ok=True)
    photo_path = base / "photo"
    with open(photo_path, "wb") as f:
        f.write(await photo.read())
    driving_path = None
    if driving_video and driving_video.filename:
        driving_path = str(base / "driving_video")
        with open(driving_path, "wb") as f:
            f.write(await driving_video.read())
    product_path = None
    if product_image and product_image.filename:
        product_path = str(base / "product_image")
        with open(product_path, "wb") as f:
            f.write(await product_image.read())

    from datetime import datetime
    payload = {
        "job_id": job_id,
        "photo_path": str(photo_path),
        "driving_video_path": driving_path,
        "product_image_path": product_path,
        "text": text,
        "consent_record_id": job_id,
        "created_at": datetime.utcnow().isoformat(),
    }
    job_store.create(job_id, payload)
    audit_log("job_created", job_id, details={"consent_given": True, "consent_record_id": job_id})
    run_pipeline.delay(payload)
    return GenerateVideoResponse(
        job_id=job_id,
        status=JobStatus.PENDING,
        message="Job enqueued",
    )


@app.get("/status/{job_id}", response_model=JobStatusResponse)
async def get_status(job_id: str):
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatusResponse(
        job_id=job["job_id"],
        status=job["status"],
        progress=job.get("progress", 0),
        current_step=job.get("current_step"),
        error=job.get("error"),
        created_at=job.get("created_at"),
        updated_at=job.get("updated_at"),
    )


@app.post("/cancel/{job_id}")
async def cancel_job(job_id: str):
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.QUALITY_FAILED):
        return JSONResponse({"job_id": job_id, "status": job["status"], "message": "Already terminal"})
    job_store.update(job_id, status=JobStatus.CANCELLED)
    audit_log("job_cancelled", job_id)
    return JSONResponse({"job_id": job_id, "status": JobStatus.CANCELLED, "message": "Cancelled"})


@app.get("/result/{job_id}", response_model=ResultResponse)
async def get_result(job_id: str):
    """Job tamamlandıysa video bilgisi; video_url yerel download endpoint'ini döner."""
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != JobStatus.COMPLETED:
        return ResultResponse(
            job_id=job_id,
            status=job["status"],
            error=job.get("error"),
        )
    audit_log("result_accessed", job_id)
    result_filename = job.get("result_key") or "output.mp4"
    local_path = get_result_local_path(job_id, result_filename)
    video_url = f"/result/{job_id}/download" if local_path.exists() else None
    return ResultResponse(
        job_id=job_id,
        status=JobStatus.COMPLETED,
        video_url=video_url,
        expires_at=None,
    )


@app.get("/result/{job_id}/download")
async def download_result(job_id: str):
    """Tamamlanan job'un video dosyasını yerel diskten sunar."""
    job = job_store.get(job_id)
    if not job or job["status"] != JobStatus.COMPLETED:
        raise HTTPException(status_code=404, detail="Job not found or not completed")
    result_filename = job.get("result_key") or "output.mp4"
    local_path = get_result_local_path(job_id, result_filename)
    if not local_path.exists():
        raise HTTPException(status_code=404, detail="Video file not found")
    return FileResponse(
        path=str(local_path),
        filename=f"clone_avatar_{job_id[:8]}.mp4",
        media_type="video/mp4",
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/metrics")
async def metrics(format: str | None = Query(None, alias="format")):
    """Job metrics (JSON or Prometheus text)."""
    if format == "prometheus":
        return PlainTextResponse(get_prometheus_text(), media_type="text/plain")
    return get_metrics()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )
