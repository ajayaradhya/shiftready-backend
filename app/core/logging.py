import logging
import sys

from app.core.context import request_id_var


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get("-")
        return True


def setup_logging() -> None:
    """Structured logging for GCP Cloud Run / Cloud Logging."""
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestIdFilter())

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s [req=%(request_id)s]: %(message)s",
        handlers=[handler],
    )
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("google.resumable_media").setLevel(logging.WARNING)
    logging.info("Logging initialized.")
