from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import settings
from app.llm.service import LLMService, get_llm_service

router = APIRouter(tags=["llm"], prefix="/llm")


class LLMCheckOut(BaseModel):
    model: str
    base_url: str
    answer: str
    duration_ms: int


@router.get("/check", response_model=LLMCheckOut)
def check_llm(llm: LLMService = Depends(get_llm_service)) -> LLMCheckOut:
    """Проверка связи с моделью."""
    answer, duration_ms = llm.ping()
    return LLMCheckOut(
        model=llm.model, base_url=settings.llm_base_url, answer=answer, duration_ms=duration_ms
    )
