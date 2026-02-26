# Clone Avatar AI

Diffusion talking-head "Pro Clone + UGC" pipeline: photo (+ optional driving video) + text → 9:16 1080×1920 talking-head video.

## Stack

- **API:** FastAPI
- **Queue:** Redis + Celery
- **Storage:** Yerel disk (`storage/inputs/`, `storage/outputs/`)
- **Pipeline:** EchoMimic (accelerated) + InstantID for identity lock

## Quick start

```bash
# Tek script (RunPod / sunucu): kurulum + Redis + API + Worker
chmod +x run.sh && ./run.sh
```

Veya elle:
```bash
pip install -r requirements.txt
# Redis çalışıyor olmalı
uvicorn api.main:app --host 0.0.0.0 --port 8000 &
celery -A workers.celery_app worker --loglevel=info
```

## Docker

```bash
docker-compose up -d redis
docker-compose up api worker
```

## API

- `POST /generate-video` — multipart: `text`, `consent_given`, `photo`; optional: `driving_video`, `product_image`, `idempotency_key`
- `GET /status/{job_id}` — job status and progress
- `POST /cancel/{job_id}` — cancel job
- `GET /result/{job_id}` — video bilgisi; `video_url`: `/result/{job_id}/download`
- `GET /result/{job_id}/download` — videoyu indir (yerel dosyadan)
- `GET /metrics` — job metrics (JSON); `?format=prometheus` for Prometheus
- `GET /health` — health check

Consent is required (`consent_given=true`). Audit log is written to `storage/audit.jsonl`. Watermark is applied in the output video.

## Environment

Copy `.env.example` to `.env` and adjust.

**Workspace (RunPod / kalıcı disk):**  
`WORKSPACE_ROOT=/workspace` verirsen storage ve venv `/workspace/storage` ile `/workspace/venv` olur; proje `/workspace/clone_avatar_ai` içinde olsa bile veri kalıcı diskte kalır. RunPod’da volume path’i: Pod için `/runpod`, serverless için `/runpod-volume`.
