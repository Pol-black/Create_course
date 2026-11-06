"""Черновик курса из фрагментов без LLM."""

import json
from pathlib import Path

from app.courses import content as C
from app.courses.draft import ChunkInput, build_draft_course

CHUNKS = json.loads((Path(__file__).parent.parent / "app/courses/example/chunks.json").read_text(encoding="utf-8"))


def test_draft_has_valid_sections_with_sources():
    draft = build_draft_course("MPI.pdf", [ChunkInput(100 + i, c["text"]) for i, c in enumerate(CHUNKS)])
    assert draft.title and draft.description and draft.goals
    assert len(draft.sections) >= len(CHUNKS) - 1
    allowed = {100 + i for i in range(len(CHUNKS))}
    for section in draft.sections:
        content = C.SectionContentIn.model_validate(section.content)
        assert content.content_md.strip()
        assert content.source_chunk_ids and set(content.source_chunk_ids) <= allowed
