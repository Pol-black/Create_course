"""
Пример готового курса без языковой модели.
"""

import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.courses import service
from app.models import Author, Chunk, Course, Document, DocumentStatus, FileType

EXAMPLE_DIR = Path(__file__).parent / "example"
EXAMPLE_FILE_NAME = "MPI (пример).pdf"


def _load(name: str) -> Any:
    return json.loads((EXAMPLE_DIR / name).read_text(encoding="utf-8"))


def create_example_course(session: Session) -> Course:
    """Создать документ, фрагменты и курс-пример. Повторный вызов возвращает уже созданный курс."""
    existing = session.scalar(
        select(Course).join(Document, Document.id == Course.document_id).where(Document.file_name == EXAMPLE_FILE_NAME)
    )
    if existing:
        return existing

    pdf = EXAMPLE_DIR / "MPI.pdf"
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    target = settings.upload_dir / f"{uuid.uuid4().hex}.pdf"
    shutil.copyfile(pdf, target)  

    chunk_data = _load("chunks.json")
    data = _load("course.json")
    document = Document(
        file_name=EXAMPLE_FILE_NAME, file_type=FileType.PDF, file_size=pdf.stat().st_size,
        file_path=str(target), status=DocumentStatus.PROCESSED, check_enabled=True,
        extracted_text="\n\n".join(c["text"] for c in chunk_data),
    )
    session.add(document)
    session.flush()
    chunks = [
        Chunk(document_id=document.id, position=c["position"], heading=c["heading"],
              page_from=c["page_from"], page_to=c["page_to"], text=c["text"])
        for c in chunk_data
    ]
    session.add_all(chunks)
    session.flush()
    chunk_id = {c.position: c.id for c in chunks}

    sections = []
    for s in data["sections"]:
        content = dict(s["content"])
        content["source_chunk_ids"] = [chunk_id[p] for p in s["chunk_positions"]]
        sections.append((s["title"], content))

    return service.create_course(
        session, document.id, data["title"], data["description"], data["goals"], sections,
        author=Author.AI, model="example", prompt_name="example",
    )
