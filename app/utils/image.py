import io
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

_executor = ThreadPoolExecutor(max_workers=2)


def _resize_jpeg(data: bytes, max_width: int, quality: int = 82) -> bytes:
    img = Image.open(io.BytesIO(data))
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
    w, h = img.size
    if w > max_width:
        new_h = max(1, round(h * max_width / w))
        img = img.resize((max_width, new_h), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


async def generate_and_store_variants(
    gcs,
    bucket: str,
    gcs_path: str,
) -> tuple[str, str]:
    """
    Download original from GCS, generate 200w + 800w JPEG variants, re-upload.
    Returns (thumb_gcs_path, medium_gcs_path).
    """
    import asyncio

    loop = asyncio.get_event_loop()
    blob_name = gcs_path.removeprefix(f"gs://{bucket}/")
    stem = blob_name.rsplit(".", 1)[0]
    thumb_blob = f"{stem}_200w.jpg"
    medium_blob = f"{stem}_800w.jpg"

    original = await loop.run_in_executor(_executor, gcs.download_bytes, bucket, blob_name)

    thumb_bytes, medium_bytes = await asyncio.gather(
        loop.run_in_executor(_executor, _resize_jpeg, original, 200),
        loop.run_in_executor(_executor, _resize_jpeg, original, 800),
    )

    await asyncio.gather(
        loop.run_in_executor(
            _executor, gcs.upload_bytes, bucket, thumb_blob, thumb_bytes, "image/jpeg"
        ),
        loop.run_in_executor(
            _executor, gcs.upload_bytes, bucket, medium_blob, medium_bytes, "image/jpeg"
        ),
    )

    return f"gs://{bucket}/{thumb_blob}", f"gs://{bucket}/{medium_blob}"
