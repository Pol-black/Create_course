from pydantic import BaseModel, Field, field_validator, model_validator


class OutlineSection(BaseModel):
    title: str = Field(min_length=1)
    chunk_ids: list[int] = Field(min_length=1)


class CourseOutline(BaseModel):
    """План курса."""

    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    goals: list[str] = Field(min_length=1)
    sections: list[OutlineSection] = Field(min_length=1)

    @field_validator("goals")
    @classmethod
    def goals_not_blank(cls, value: list[str]) -> list[str]:
        cleaned = [g.strip() for g in value if g and g.strip()]
        if not cleaned:
            raise ValueError("список целей пуст")
        return cleaned


class Term(BaseModel):
    term: str = Field(min_length=1)
    definition: str = Field(min_length=1)


class Question(BaseModel):
    """Вопрос для самопроверки. Без баллов и подсчёта результатов."""

    question: str = Field(min_length=1)
    options: list[str] = Field(min_length=2)
    correct_index: int = Field(ge=0)
    explanation: str = Field(min_length=1)

    @model_validator(mode="after")
    def correct_index_exists(self) -> "Question":
        if self.correct_index >= len(self.options):
            raise ValueError("correct_index указывает на несуществующий вариант")
        return self


class SectionContent(BaseModel):
    """Содержимое раздела курса."""

    title: str = Field(min_length=1)
    intro: str = Field(min_length=1)
    content_md: str = Field(min_length=1)
    terms: list[Term] = []
    summary: list[str] = Field(min_length=1)
    questions: list[Question] = []
    source_chunk_ids: list[int] = Field(min_length=1)
    missing_info: list[str] = []
