from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter()


def check_db(db: Session) -> JSONResponse:
    """Проверка связи с бд и возрат готового ответа"""
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse(status_code=503, content={"status": "error", "db": "unavailable"})
    return JSONResponse(content={"status": "ok", "db": "ok"})


# liveness: процесс жив
@router.get("/health/live")
def live() -> dict:
    return {"status": "ok"}


# readiness: готов принимать запросы
@router.get("/health/ready")
def ready(db: Session = Depends(get_db)) -> JSONResponse:
    return check_db(db)


@router.get("/health")
def health(db: Session = Depends(get_db)) -> JSONResponse:
    return check_db(db)