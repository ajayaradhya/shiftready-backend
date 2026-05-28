import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.context import request_id_var

logger = logging.getLogger(__name__)

SLOW_REQUEST_THRESHOLD_S = 2.0


def register_middleware(app: FastAPI) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def correlation_and_timing(request: Request, call_next):
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        token = request_id_var.set(req_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            duration = time.perf_counter() - start
            request_id_var.reset(token)

        response.headers["X-Request-ID"] = req_id
        response.headers["X-Process-Time"] = f"{duration:.4f}s"

        log_fn = logger.warning if duration > SLOW_REQUEST_THRESHOLD_S else logger.info
        log_fn(
            "%s %s | %s | %.4fs | req=%s",
            request.method,
            request.url.path,
            response.status_code,
            duration,
            req_id,
        )
        return response
