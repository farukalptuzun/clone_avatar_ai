"""Storage: yerel disk (çıktılar); S3 fonksiyonları opsiyonel."""
from pathlib import Path

import boto3
from botocore.config import Config

from shared.config import settings


def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        use_ssl=settings.s3_use_ssl,
        config=Config(signature_version="s3v4"),
    )


def ensure_bucket(client=None):
    client = client or get_s3_client()
    try:
        client.head_bucket(Bucket=settings.s3_bucket)
    except Exception:
        client.create_bucket(Bucket=settings.s3_bucket)


def upload_file(
    local_path: str | Path,
    s3_key: str,
    content_type: str | None = None,
    client=None,
) -> str:
    client = client or get_s3_client()
    ensure_bucket(client)
    extra = {"ContentType": content_type} if content_type else {}
    client.upload_file(str(local_path), settings.s3_bucket, s3_key, ExtraArgs=extra)
    return f"s3://{settings.s3_bucket}/{s3_key}"


def download_file(s3_key: str, local_path: str | Path, client=None) -> Path:
    client = client or get_s3_client()
    Path(local_path).parent.mkdir(parents=True, exist_ok=True)
    client.download_file(settings.s3_bucket, s3_key, str(local_path))
    return Path(local_path)


def generate_presigned_url(
    s3_key: str,
    expiration: int | None = None,
    client=None,
) -> str:
    client = client or get_s3_client()
    expiration = expiration or settings.signed_url_ttl_seconds
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": s3_key},
        ExpiresIn=expiration,
    )


def job_input_path(job_id: str, filename: str) -> str:
    return f"{settings.inputs_prefix}/{job_id}/{filename}"


def job_output_path(job_id: str, filename: str) -> str:
    """S3 key (when using S3)."""
    return f"{settings.outputs_prefix}/{job_id}/{filename}"


def get_result_local_path(job_id: str, filename: str = "output.mp4") -> Path:
    """Yerel diskte çıktı dosyasının tam yolu (S3 kullanılmıyor)."""
    return Path(settings.storage_base_path) / settings.outputs_prefix / job_id / filename
