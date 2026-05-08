import logging
import sys


def setup_logging() -> None:
    """Configures centralized logging optimized for GCP Cloud Run / Cloud Logging."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("google.resumable_media").setLevel(logging.WARNING)
    logging.info("Logging initialized.")
