import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_JOB_NAME = "frame-extractor"
_REGION = "australia-southeast1"


async def trigger_frame_extraction(event_id: str) -> None:
    """
    Fire the frame-extraction job for a sale event.
    Local dev (K_SERVICE absent): spawns main.py as subprocess — non-blocking.
    Cloud Run: invokes the Cloud Run Job via the Run v2 API — awaits job start only.
    """
    if os.getenv("K_SERVICE"):
        await _trigger_cloud_run_job(event_id)
    else:
        _trigger_local_subprocess(event_id)


def _trigger_local_subprocess(event_id: str) -> None:
    import subprocess

    script = Path(__file__).parents[2] / "jobs" / "frame_extractor" / "main.py"
    if not script.exists():
        logger.warning(f"frame_extractor script not found at {script} — skipping local trigger")
        return

    env = {**os.environ, "EVENT_ID": event_id}
    subprocess.Popen([sys.executable, str(script)], env=env)
    logger.info(f"frame_extraction | local subprocess started | event={event_id} script={script}")


async def _trigger_cloud_run_job(event_id: str) -> None:
    from google.cloud import run_v2
    from app.core.config import settings

    client = run_v2.JobsAsyncClient()
    job_name = (
        f"projects/{settings.gcp_project_id}"
        f"/locations/{_REGION}"
        f"/jobs/{_JOB_NAME}"
    )
    request = run_v2.RunJobRequest(
        name=job_name,
        overrides=run_v2.RunJobRequest.Overrides(
            container_overrides=[
                run_v2.RunJobRequest.Overrides.ContainerOverride(
                    env=[run_v2.EnvVar(name="EVENT_ID", value=event_id)]
                )
            ]
        ),
    )
    operation = await client.run_job(request=request)
    logger.info(
        f"frame_extraction | Cloud Run Job triggered | "
        f"event={event_id} operation={operation.operation.name}"
    )
