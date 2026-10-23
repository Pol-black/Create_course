import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.exc import SQLAlchemyError

from app.db import SessionLocal
from app.models import LogLevel, ProcessingLog

logger = logging.getLogger("app.processing")

CONSOLE_LEVELS = {
    LogLevel.INFO: logging.INFO,
    LogLevel.WARN: logging.WARNING,
    LogLevel.ERROR: logging.ERROR,
}


def write_log(
    document_id: int,
    stage: str,
    message: str,
    level: LogLevel = LogLevel.INFO,
    duration_ms: int | None = None,
) -> None:
    logger.log(
        CONSOLE_LEVELS[level],
        "document=%s stage=%s %s%s",
        document_id, stage, message,
        f" ({duration_ms} ms)" if duration_ms is not None else "",
    )

    try:
        with SessionLocal() as session:
            session.add(
                ProcessingLog(
                    document_id=document_id,
                    stage=stage,
                    level=level,
                    message=message,
                    duration_ms=duration_ms,
                )
            )
            session.commit()
    except SQLAlchemyError:
        logger.exception("Не удалось записать processing_log для document=%s", document_id)

@contextmanager
def log_stage(document_id: int, stage: str, title: str) -> Iterator[None]:
    """Замерка время этапа и запись в журнал результат: готово или ошибка."""
    start = time.perf_counter()
    try:
        yield
    except Exception as exc:
        duration_ms = round((time.perf_counter() - start) * 1000)
        write_log(document_id, stage, f"{title}: ошибка: {exc}", LogLevel.ERROR, duration_ms)
        raise
    duration_ms = round((time.perf_counter() - start) * 1000)
    write_log(document_id, stage, f"{title}: готово", LogLevel.INFO, duration_ms)