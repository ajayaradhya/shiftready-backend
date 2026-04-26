import logging
import sys

def setup_logging():
    """
    Configures centralized logging for the ShiftReady Monolith.
    Optimized for GCP Cloud Run / Cloud Logging.
    """
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    
    # Configure the root logger
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )

    # Set specific levels for noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("google.resumable_media").setLevel(logging.WARNING)

    logging.info("Logging initialized: Centralized configuration applied.")