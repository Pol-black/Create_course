import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import courses, documents, health, llm
from app.config import settings
from app.errors import register_error_handlers
from app.journal.console import setup_logging
from app.journal.request_log import register_request_logging


setup_logging(settings.log_level)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Документы, которые обрабатывались в момент перезапуска, больше не обрабатываются
    try:
        from app.processing import recover_interrupted

        stuck = recover_interrupted()
        if stuck:
            logging.getLogger("app").warning("Прерванных обработок: %d, помечены ошибкой", stuck)
    except Exception:
        logging.getLogger("app").exception("Не удалось проверить прерванные обработки")
    yield


app = FastAPI(title="Прототип API", lifespan=lifespan)


app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)


register_request_logging(app)
register_error_handlers(app)


app.include_router(health.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(llm.router, prefix="/api")
app.include_router(courses.router, prefix="/api")
