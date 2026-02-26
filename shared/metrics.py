"""Simple metrics: job counts and latency for Prometheus/observability."""
from shared.config import settings

REDIS_METRICS_PREFIX = "clone_avatar:metrics:"


def _redis():
    try:
        import redis
        return redis.from_url(settings.redis_url, decode_responses=True)
    except Exception:
        return None


def increment_job_completed(duration_sec: float) -> None:
    r = _redis()
    if r:
        try:
            r.incr(REDIS_METRICS_PREFIX + "jobs_completed")
            r.incrbyfloat(REDIS_METRICS_PREFIX + "total_duration_sec", duration_sec)
        except Exception:
            pass


def increment_job_failed() -> None:
    r = _redis()
    if r:
        try:
            r.incr(REDIS_METRICS_PREFIX + "jobs_failed")
        except Exception:
            pass


def increment_quality_failed() -> None:
    r = _redis()
    if r:
        try:
            r.incr(REDIS_METRICS_PREFIX + "jobs_quality_failed")
        except Exception:
            pass


def get_metrics() -> dict:
    r = _redis()
    if not r:
        return {"jobs_completed": 0, "jobs_failed": 0, "jobs_quality_failed": 0, "total_duration_sec": 0}
    try:
        return {
            "jobs_completed": int(r.get(REDIS_METRICS_PREFIX + "jobs_completed") or 0),
            "jobs_failed": int(r.get(REDIS_METRICS_PREFIX + "jobs_failed") or 0),
            "jobs_quality_failed": int(r.get(REDIS_METRICS_PREFIX + "jobs_quality_failed") or 0),
            "total_duration_sec": float(r.get(REDIS_METRICS_PREFIX + "total_duration_sec") or 0),
        }
    except Exception:
        return {"jobs_completed": 0, "jobs_failed": 0, "jobs_quality_failed": 0, "total_duration_sec": 0}


def get_prometheus_text() -> str:
    m = get_metrics()
    lines = [
        "# HELP clone_avatar_jobs_completed Total completed jobs",
        "# TYPE clone_avatar_jobs_completed counter",
        f"clone_avatar_jobs_completed {m['jobs_completed']}",
        "# HELP clone_avatar_jobs_failed Total failed jobs",
        "# TYPE clone_avatar_jobs_failed counter",
        f"clone_avatar_jobs_failed {m['jobs_failed']}",
        "# HELP clone_avatar_jobs_quality_failed Total quality-failed jobs",
        "# TYPE clone_avatar_jobs_quality_failed counter",
        f"clone_avatar_jobs_quality_failed {m['jobs_quality_failed']}",
        "# HELP clone_avatar_total_duration_sec Total pipeline duration seconds",
        "# TYPE clone_avatar_total_duration_sec counter",
        f"clone_avatar_total_duration_sec {m['total_duration_sec']}",
    ]
    return "\n".join(lines) + "\n"
