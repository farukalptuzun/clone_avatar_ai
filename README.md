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

**Ngrok (API’yi canlıya alma):**  
`.env` içine `NGROK_AUTHTOKEN=<token>` ekle; `run.sh` API’yi başlattıktan sonra ngrok’u kurar (yoksa indirir), authtoken’ı yazar ve `ngrok http 8000` ile tüneli açar. Canlı URL ngrok çıktısında veya yerel `http://127.0.0.1:4040` arayüzünde görünür.

**EchoMimic (gerçek talking-head):**  
Varsayılan davranış EchoMimic yoksa placeholder video (sabit kare) üretir. Gerçek konuşan kafa için: [EchoMimic](https://github.com/antgroup/echomimic) reposunu klonlayın, **EchoMimic içinde kendi venv'inizi oluşturup** (PyTorch, vb. EchoMimic bağımlılıklarını) kurun. Pretrained ağırlıkları indirmek için EchoMimic repo kökünde: `git lfs install` sonra `git clone https://huggingface.co/BadToBest/EchoMimic pretrained_weights`. `.env` içinde `ECHOMIMIC_PATH=/path/to/echomimic` ve **`ECHOMIMIC_PYTHON=/path/to/echomimic/venv/bin/python`** tanımlayın.

---

## Pull sonrası: Driving video kullanımı

Kodu `git pull` ile güncelledikten sonra **driving video** (referans hareket videosu) ile üretim yapmak için:

### 1. Projeyi güncelle

```bash
cd /path/to/clone_avatar_ai   # veya RunPod’da /workspace/clone_avatar_ai
git pull
```

### 2. EchoMimic’i kur (henüz yoksa)

- [EchoMimic](https://github.com/antgroup/echomimic) reposunu klonla (ör. `/workspace/echomimic`).
- Kendi venv’ini oluştur, `pip install -r requirements.txt` (EchoMimic’in `requirements.txt`).
- Ağırlıkları indir (ses + driving video için gerekli tüm `.pth` dosyaları bu repoda):

  ```bash
  cd /workspace/echomimic
  git lfs install
  git clone https://huggingface.co/BadToBest/EchoMimic pretrained_weights
  ```

  Clone sonrası `pretrained_weights/` içinde hem normal hem **`*_pose.pth`** dosyaları (denoising_unet_pose.pth, reference_unet_pose.pth, face_locator_pose.pth, motion_module_pose.pth) gelir. Driving video kullanacaksan bu dört pose dosyasının da orada olduğundan emin ol; eksikse [Hugging Face repo](https://huggingface.co/BadToBest/EchoMimic) üzerinden indirip `pretrained_weights/` içine koy.

### 3. `.env` ayarları

`.env.example`’ı kopyalayıp `.env` yaptıysan, EchoMimic path’lerini ekle:

```bash
cp .env.example .env
# .env içinde düzenle:
ECHOMIMIC_PATH=/workspace/echomimic
ECHOMIMIC_PYTHON=/workspace/echomimic/venv/bin/python
```

RunPod’da dizin farklıysa (ör. `/runpod/echomimic`) path’i ona göre yaz.

### 4. Servisleri yeniden başlat

```bash
# run.sh kullanıyorsan
./run.sh

# veya elle
uvicorn api.main:app --host 0.0.0.0 --port 8000 &
celery -A workers.celery_app worker --loglevel=info
```

### 5. API’ye driving video gönder

- `POST /generate-video` çağrısında **`driving_video`** alanına bir video dosyası (mp4 vb.) yükle.
- Diğer alanlar aynı: `text`, `consent_given`, `photo` (zorunlu).
- Pipeline: videodan yüz landmark’larını çıkarır, ref foto + ses ile birlikte EchoMimic **pose** modunda kullanır; böylece driving video gerçekten üretimde kullanılır.

**Özet:** Pull → EchoMimic + pretrained + pose ağırlıkları → `.env`’de `ECHOMIMIC_PATH` ve `ECHOMIMIC_PYTHON` → servisleri yeniden başlat → istekte `driving_video` yükle.
