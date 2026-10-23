from fastapi import FastAPI

from app.api import health
from app.config import settings
from app.errors import register_error_handlers
from app.journal.console import setup_logging
from app.journal.request_log import register_request_logging

setup_logging(settings.log_level)

app = FastAPI(title="Прототип API")

register_request_logging(app)
register_error_handlers(app)

app.include_router(health.router, prefix="/api")