import logging
import time
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

SLOW_THRESHOLD_S = 0.5


@asynccontextmanager
async def timed_op(label: str):
    """Log a warning if the enclosed async operation exceeds SLOW_THRESHOLD_S."""
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        if elapsed > SLOW_THRESHOLD_S:
            logger.warning("SLOW_FIRESTORE_OP op=%s elapsed=%.3fs", label, elapsed)
        else:
            logger.debug("firestore_op op=%s elapsed=%.3fs", label, elapsed)
