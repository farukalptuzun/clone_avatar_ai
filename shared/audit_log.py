"""Audit log for consent, job lifecycle, and result access (clone/usage compliance)."""
import json
from datetime import datetime
from pathlib import Path

from shared.config import settings

_AUDIT_PATH = Path(settings.storage_base_path) / "audit.jsonl"


def _ensure_audit_dir():
    _AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)


def audit_log(
    action: str,
    job_id: str,
    user_id: str | None = None,
    details: dict | None = None,
) -> None:
    """Append one audit entry. Actions: job_created, job_cancelled, job_completed, job_failed, quality_failed, result_accessed."""
    _ensure_audit_dir()
    entry = {
        "ts": datetime.utcnow().isoformat() + "Z",
        "action": action,
        "job_id": job_id,
        "user_id": user_id,
        "details": details or {},
    }
    with open(_AUDIT_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
