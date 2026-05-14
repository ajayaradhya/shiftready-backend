#!/usr/bin/env python3
"""
Cloud Run Job: Frame Extractor
Triggered after AI extraction completes. Downloads the sale video from GCS,
extracts one representative JPEG frame per item at its recorded timestamp,
and writes the GCS path back to each item document in Firestore.

Required env vars:
  EVENT_ID            - Firestore sale event ID
  GCP_PROJECT_ID      - GCP project
  GCP_UPLOAD_BUCKET   - GCS bucket (video source + frame destination)

Optional:
  GOOGLE_APPLICATION_CREDENTIALS - path to SA JSON (local dev only)
"""
import logging
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from google.cloud import firestore, storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("frame_extractor")


def download_video(gcs_client: storage.Client, gcs_uri: str, dest: Path) -> None:
    parts = gcs_uri.replace("gs://", "").split("/", 1)
    bucket_name, blob_name = parts[0], parts[1]
    blob = gcs_client.bucket(bucket_name).blob(blob_name)
    blob.download_to_filename(str(dest))
    size_mb = dest.stat().st_size / 1_000_000
    logger.info(f"video downloaded | uri={gcs_uri} size={size_mb:.1f}MB")


def extract_frame(video_path: Path, timestamp: float, output_path: Path) -> bool:
    """
    Fast-seek to timestamp then grab the first decoded frame.
    Pre-input -ss is fast (keyframe seek); acceptable accuracy for multi-second windows.
    """
    ffmpeg_bin = os.environ.get("FFMPEG_PATH", "ffmpeg")
    cmd = [
        ffmpeg_bin, "-y",
        "-ss", f"{timestamp:.3f}",
        "-i", str(video_path),
        "-frames:v", "1",
        "-an",                # Ignore audio stream for faster extraction
        "-q:v", "2",          # JPEG quality 2 = near-lossless (~95% quality)
        str(output_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(
                f"ffmpeg failed | ts={timestamp:.3f} | "
                f"stderr={result.stderr[-500:] if result.stderr else 'empty'}"
            )
            return False
    except (FileNotFoundError, PermissionError):
        logger.error(
            f"ffmpeg execution failed: '{ffmpeg_bin}'. "
            "On Windows, ensure FFMPEG_PATH points to the ffmpeg.exe file, not just the bin folder."
        )
        return False
    logger.debug(f"frame extracted | ts={timestamp:.3f} → {output_path.name}")
    return True


def upload_frame(
    gcs_client: storage.Client,
    bucket_name: str,
    local_path: Path,
    gcs_path: str,
) -> str:
    blob = gcs_client.bucket(bucket_name).blob(gcs_path)
    blob.upload_from_filename(str(local_path), content_type="image/jpeg")
    return f"gs://{bucket_name}/{gcs_path}"


def verify_ffmpeg() -> bool:
    ffmpeg_bin = os.environ.get("FFMPEG_PATH", "ffmpeg")
    try:
        subprocess.run([ffmpeg_bin, "-version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError, PermissionError) as e:
        if isinstance(e, PermissionError):
            logger.error(
                f"Permission denied for '{ffmpeg_bin}'. "
                "Check if FFMPEG_PATH points to a directory. It must point to the executable file (ffmpeg.exe)."
            )
        return False


def process_event(event_id: str, project_id: str, upload_bucket: str) -> None:
    db = firestore.Client(project=project_id)
    gcs = storage.Client(project=project_id)

    event_ref = db.collection("saleEvents").document(event_id)
    event_doc = event_ref.get()
    if not event_doc.exists:
        logger.error(f"sale event not found | event={event_id}")
        sys.exit(1)

    gcs_uri: str | None = event_doc.to_dict().get("videoUrl")
    if not gcs_uri or not gcs_uri.startswith("gs://"):
        logger.error(f"invalid or missing videoUrl | event={event_id} url={gcs_uri!r}")
        sys.exit(1)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        video_path = tmp / "video.mp4"

        logger.info(f"starting frame extraction | event={event_id}")
        download_video(gcs, gcs_uri, video_path)

        success_count = 0
        fail_count = 0

        for bundle_doc in event_ref.collection("bundles").stream():
            bundle_id = bundle_doc.id
            for item_doc in bundle_doc.reference.collection("items").stream():
                item_id = item_doc.id
                item_data = item_doc.to_dict()
                item_name = item_data.get("name", "unnamed")
                timestamp = item_data.get("video_timestamp")

                if timestamp is None:
                    logger.warning(
                        f"skipping item — no timestamp | "
                        f"event={event_id} bundle={bundle_id} item={item_id} name={item_name!r}"
                    )
                    fail_count += 1
                    continue

                frame_local = tmp / f"frame_{item_id}.jpg"

                # Future-Proof Pathing: All assets for an item are now grouped in one folder
                gcs_frame_path = f"sales/{event_id}/items/{item_id}/extracted_frame.jpg"

                try:
                    if not extract_frame(video_path, float(timestamp), frame_local):
                        fail_count += 1
                        continue

                    full_gcs_path = upload_frame(gcs, upload_bucket, frame_local, gcs_frame_path)

                    image_obj = {
                        "id": f"ext_{item_id}",
                        "gcs_path": full_gcs_path,
                        "source": "frame_extract",
                        "is_cover": True,
                        "uploaded_at": datetime.now(timezone.utc).isoformat(),
                    }

                    item_doc.reference.update({
                        "images": firestore.ArrayUnion([image_obj]),
                    })

                    logger.info(
                        f"frame saved | event={event_id} item={item_id} "
                        f"name={item_name!r} ts={timestamp} path={full_gcs_path}"
                    )
                    success_count += 1

                except Exception:
                    logger.exception(
                        f"frame extraction failed | event={event_id} item={item_id} name={item_name!r}"
                    )
                    fail_count += 1

        event_ref.update({
            "frameExtractionCompletedAt": firestore.SERVER_TIMESTAMP,
            "frameExtractionStats": {"success": success_count, "failed": fail_count},
        })

        logger.info(
            f"frame extraction complete | event={event_id} "
            f"success={success_count} failed={fail_count}"
        )

    if fail_count > 0 and success_count == 0:
        logger.error(f"all items failed | event={event_id}")
        sys.exit(1)


if __name__ == "__main__":
    event_id = os.environ.get("EVENT_ID", "").strip()
    project_id = os.environ.get("GCP_PROJECT_ID", "").strip()
    upload_bucket = os.environ.get("GCP_UPLOAD_BUCKET", "").strip()

    missing = [k for k, v in {
        "EVENT_ID": event_id,
        "GCP_PROJECT_ID": project_id,
        "GCP_UPLOAD_BUCKET": upload_bucket,
    }.items() if not v]

    if missing:
        logger.error(f"missing required env vars: {', '.join(missing)}")
        sys.exit(1)

    if not verify_ffmpeg():
        logger.error(
            f"ffmpeg not found or not working: '{os.environ.get('FFMPEG_PATH', 'ffmpeg')}'. "
            "For local dev, add it to your PATH. For production, install it in your Dockerfile (apt-get install ffmpeg)."
        )
        sys.exit(1)

    process_event(event_id, project_id, upload_bucket)
