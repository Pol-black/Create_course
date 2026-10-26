import logging
import time
import uuid

from fastapi import FastAPI, Request, Response

from app.errors import error_response

logger = logging.getLogger("app.request")

QUIET_PATHS = {"/api/health", "/api/health/live", "/api/health/ready"}


def register_request_logging(app: FastAPI) -> None:
    @app.middleware("http")
    async def log_requests(request: Request, call_next) -> Response:
        request_id = uuid.uuid4().hex[:8]
        request.state.request_id = request_id
        start = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - start) * 1000)
            logger.exception(
                "%s %s -> 500 (%d ms) [%s]",
                request.method, request.url.path, duration_ms, request_id,
            )
            response = error_response(
                request, 500, "internal_error", "Внутренняя ошибка сервера"
            )
            response.headers["X-Request-ID"] = request_id
            return response

        duration_ms = round((time.perf_counter() - start) * 1000)
        if response.status_code >= 500:
            level = logging.ERROR
        elif response.status_code >= 400:
            level = logging.WARNING
        elif request.url.path in QUIET_PATHS:
            level = logging.DEBUG
        else:
            level = logging.INFO
        logger.log(
            level,
            "%s %s -> %d (%d ms) [%s]",
            request.method, request.url.path, response.status_code, duration_ms, request_id,
        )
        response.headers["X-Request-ID"] = request_id
        return response