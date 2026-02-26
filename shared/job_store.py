"""Job state store: Redis-backed so API and workers share state. Falls back to in-memory if Redis unavailable."""
from datetime import datetime
from typing import Any

from shared.config import settings
from shared.schemas import JobStatus

REDIS_KEY_PREFIX = "clone_avatar:job:"


def _serialize_dt(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


class RedisJobStore:
    """Store job state in Redis so API and Celery workers share the same state."""

    def __init__(self, redis_url: str | None = None):
        self._redis_url = redis_url or settings.redis_url
        self._client = None

    def _get_client(self):
        if self._client is None:
            import redis
            self._client = redis.from_url(self._redis_url, decode_responses=True)
        return self._client

    def create(self, job_id: str, payload: dict[str, Any] | None = None) -> None:
        now = datetime.utcnow()
        data = {
            "job_id": job_id,
            "status": JobStatus.PENDING,
            "progress": 0.0,
            "current_step": None,
            "error": None,
            "created_at": _serialize_dt(now),
            "updated_at": _serialize_dt(now),
            "payload": payload or {},
            "result_key": None,
            "metrics": None,
        }
        try:
            import json
            data["status"] = data["status"].value if hasattr(data["status"], "value") else str(data["status"])
            r = self._get_client()
            r.set(REDIS_KEY_PREFIX + job_id, json.dumps(data), ex=86400 * 7)
        except Exception:
            pass

    def update(
        self,
        job_id: str,
        status: JobStatus | None = None,
        progress: float | None = None,
        current_step: str | None = None,
        error: str | None = None,
        result_key: str | None = None,
        metrics: dict | None = None,
    ) -> None:
        job = self.get(job_id)
        if not job:
            return
        if status is not None:
            job["status"] = status
        if progress is not None:
            job["progress"] = progress
        if current_step is not None:
            job["current_step"] = current_step
        if error is not None:
            job["error"] = error
        if result_key is not None:
            job["result_key"] = result_key
        if metrics is not None:
            job["metrics"] = {**(job.get("metrics") or {}), **metrics}
        job["updated_at"] = _serialize_dt(datetime.utcnow())
        try:
            import json
            if isinstance(job.get("status"), JobStatus):
                job["status"] = job["status"].value
            r = self._get_client()
            r.set(REDIS_KEY_PREFIX + job_id, json.dumps(job, default=str), ex=86400 * 7)
        except Exception:
            pass

    def get(self, job_id: str) -> dict[str, Any] | None:
        try:
            r = self._get_client()
            raw = r.get(REDIS_KEY_PREFIX + job_id)
            if not raw:
                return None
            data = __import__("json").loads(raw)
            if data.get("created_at"):
                data["created_at"] = _parse_dt(data["created_at"]) or data["created_at"]
            if data.get("updated_at"):
                data["updated_at"] = _parse_dt(data["updated_at"]) or data["updated_at"]
            if data.get("status") and isinstance(data["status"], str):
                try:
                    data["status"] = JobStatus(data["status"])
                except ValueError:
                    pass
            return data
        except Exception:
            return None

    def delete(self, job_id: str) -> None:
        try:
            self._get_client().delete(REDIS_KEY_PREFIX + job_id)
        except Exception:
            pass


class InMemoryJobStore:
    def __init__(self):
        self._jobs: dict[str, dict[str, Any]] = {}

    def create(self, job_id: str, payload: dict[str, Any] | None = None) -> None:
        now = datetime.utcnow()
        self._jobs[job_id] = {
            "job_id": job_id,
            "status": JobStatus.PENDING,
            "progress": 0.0,
            "current_step": None,
            "error": None,
            "created_at": now,
            "updated_at": now,
            "payload": payload or {},
            "result_key": None,
            "metrics": None,
        }

    def update(
        self,
        job_id: str,
        status: JobStatus | None = None,
        progress: float | None = None,
        current_step: str | None = None,
        error: str | None = None,
        result_key: str | None = None,
        metrics: dict | None = None,
    ) -> None:
        if job_id not in self._jobs:
            return
        job = self._jobs[job_id]
        if status is not None:
            job["status"] = status
        if progress is not None:
            job["progress"] = progress
        if current_step is not None:
            job["current_step"] = current_step
        if error is not None:
            job["error"] = error
        if result_key is not None:
            job["result_key"] = result_key
        if metrics is not None:
            job["metrics"] = {**(job.get("metrics") or {}), **metrics}
        job["updated_at"] = datetime.utcnow()

    def get(self, job_id: str) -> dict[str, Any] | None:
        return self._jobs.get(job_id)

    def delete(self, job_id: str) -> None:
        self._jobs.pop(job_id, None)


def _make_job_store():
    try:
        store = RedisJobStore()
        store._get_client().ping()
        return store
    except Exception:
        return InMemoryJobStore()


job_store = _make_job_store()
