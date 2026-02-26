"""Pipeline tasks: chain input_prep -> tts -> video_gen -> quality_check -> postprocess -> ugc_pack."""
from datetime import datetime

from workers.celery_app import app
from shared.audit_log import audit_log
from shared.job_store import job_store
from shared.metrics import increment_job_completed, increment_job_failed, increment_quality_failed
from shared.schemas import JobStatus


def _update_job(job_id: str, status: JobStatus, progress: float = 0.0, current_step: str | None = None):
    job_store.update(job_id, status=status, progress=progress, current_step=current_step)


@app.task(bind=True)
def run_pipeline(self, payload: dict):
    """Run full pipeline: prep -> TTS -> video -> quality -> postprocess -> UGC."""
    job_id = payload.get("job_id")
    if not job_id:
        return {"error": "missing job_id"}
    job = job_store.get(job_id)
    if not job or job.get("status") == JobStatus.CANCELLED:
        return {"status": "cancelled"}

    try:
        # 1. Input prep
        _update_job(job_id, JobStatus.PREPARING, 0.1, "input_prep")
        from workers.stages.input_prep import run_input_prep
        prep_result = run_input_prep(payload)
        if prep_result.get("error"):
            job_store.update(job_id, status=JobStatus.FAILED, error=prep_result["error"])
            audit_log("job_failed", job_id, details={"step": "input_prep", "error": prep_result["error"]})
            increment_job_failed()
            return prep_result
        payload.update(prep_result)

        # 2. TTS
        _update_job(job_id, JobStatus.TTS, 0.25, "tts")
        from workers.stages.tts_stage import run_tts
        tts_result = run_tts(payload)
        if tts_result.get("error"):
            job_store.update(job_id, status=JobStatus.FAILED, error=tts_result["error"])
            audit_log("job_failed", job_id, details={"step": "tts", "error": tts_result["error"]})
            increment_job_failed()
            return tts_result
        payload.update(tts_result)

        # 3. Video gen
        _update_job(job_id, JobStatus.VIDEO_GEN, 0.4, "video_gen")
        from workers.stages.video_gen import run_video_gen
        video_result = run_video_gen(payload)
        if video_result.get("error"):
            job_store.update(job_id, status=JobStatus.FAILED, error=video_result["error"])
            audit_log("job_failed", job_id, details={"step": "video_gen", "error": video_result["error"]})
            increment_job_failed()
            return video_result
        payload.update(video_result)

        # 4. Quality check (may resample)
        _update_job(job_id, JobStatus.QUALITY_CHECK, 0.65, "quality_check")
        from workers.stages.quality_gate import run_quality_gate
        quality_result = run_quality_gate(payload)
        if quality_result.get("error"):
            job_store.update(job_id, status=JobStatus.QUALITY_FAILED, error=quality_result.get("error"))
            audit_log("quality_failed", job_id, details={"error": quality_result.get("error")})
            increment_quality_failed()
            return quality_result
        payload.update(quality_result)

        # 5. Postprocess
        _update_job(job_id, JobStatus.POSTPROCESS, 0.8, "postprocess")
        from workers.stages.postprocess import run_postprocess
        post_result = run_postprocess(payload)
        if post_result.get("error"):
            job_store.update(job_id, status=JobStatus.FAILED, error=post_result["error"])
            audit_log("job_failed", job_id, details={"step": "postprocess", "error": post_result["error"]})
            increment_job_failed()
            return post_result
        payload.update(post_result)

        # 6. UGC pack
        _update_job(job_id, JobStatus.UGC_PACK, 0.95, "ugc_pack")
        from workers.stages.ugc_pack import run_ugc_pack
        ugc_result = run_ugc_pack(payload)
        if ugc_result.get("error"):
            job_store.update(job_id, status=JobStatus.FAILED, error=ugc_result["error"])
            audit_log("job_failed", job_id, details={"step": "ugc_pack", "error": ugc_result["error"]})
            increment_job_failed()
            return ugc_result

        job = job_store.get(job_id)
        created = job.get("created_at") if job else None
        if not created and payload.get("created_at"):
            try:
                created = datetime.fromisoformat(payload["created_at"].replace("Z", "+00:00"))
            except Exception:
                created = datetime.utcnow()
        if not created:
            created = datetime.utcnow()
        duration_sec = (datetime.utcnow() - created).total_seconds() if isinstance(created, datetime) else 0
        metrics = {
            "duration_sec": duration_sec,
            "quality_pass": quality_result.get("quality_pass", True),
            "face_mean_distance": quality_result.get("face_mean_distance"),
        }
        job_store.update(
            job_id,
            status=JobStatus.COMPLETED,
            progress=1.0,
            current_step=None,
            result_key=ugc_result.get("result_key", "output.mp4"),
            metrics=metrics,
        )
        audit_log("job_completed", job_id, details=metrics)
        increment_job_completed(duration_sec)
        return {"status": "completed", "job_id": job_id}
    except Exception as e:
        job_store.update(job_id, status=JobStatus.FAILED, error=str(e))
        audit_log("job_failed", job_id, details={"step": "pipeline", "error": str(e)})
        increment_job_failed()
        raise
