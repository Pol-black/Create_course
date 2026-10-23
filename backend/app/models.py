import enum
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    FetchedValue,
    ForeignKey,
    Identity,
    Integer,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# Справочники статусов
class FileType(str, enum.Enum):
    PDF = "PDF"
    DOCX = "DOCX"
    TXT = "TXT"


class DocumentStatus(str, enum.Enum):
    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"


class CourseStatus(str, enum.Enum):
    GENERATING = "GENERATING"
    READY = "READY"
    FAILED = "FAILED"


class SectionStatus(str, enum.Enum):
    GENERATING = "GENERATING"
    READY = "READY"
    HAS_ISSUES = "HAS_ISSUES"
    FAILED = "FAILED"


class Author(str, enum.Enum):
    AI = "AI"
    USER = "USER"


class LogLevel(str, enum.Enum):
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"


file_type_enum = ENUM(FileType, name="file_type_enum", create_type=False)
document_status_enum = ENUM(DocumentStatus, name="document_status_enum", create_type=False)
course_status_enum = ENUM(CourseStatus, name="course_status_enum", create_type=False)
section_status_enum = ENUM(SectionStatus, name="section_status_enum", create_type=False)
author_enum = ENUM(Author, name="author_enum", create_type=False)
log_level_enum = ENUM(LogLevel, name="log_level_enum", create_type=False)


# Общие колонки 
def id_column() -> Mapped[int]:
    return mapped_column(BigInteger, Identity(always=True), primary_key=True)


def created_at_column() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def updated_at_column() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        server_onupdate=FetchedValue(),
        nullable=False,
    )


# Связь "версия раздела" и "фрагменты-источники"
section_version_chunk = Table(
    "section_version_chunk",
    Base.metadata,
    Column(
        "section_version_id",
        BigInteger,
        ForeignKey("section_version.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("chunk_id", BigInteger, ForeignKey("chunk.id", ondelete="CASCADE"), primary_key=True),
)


# Документ
class Document(Base):
    __tablename__ = "document"

    id: Mapped[int] = id_column()
    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    file_type: Mapped[FileType | None] = mapped_column(file_type_enum)
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    file_path: Mapped[str | None] = mapped_column(Text)
    status: Mapped[DocumentStatus] = mapped_column(document_status_enum, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    check_enabled: Mapped[bool] = mapped_column(nullable=False)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document",
        order_by="Chunk.position",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    courses: Mapped[list["Course"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    logs: Mapped[list["ProcessingLog"]] = relationship(
        back_populates="document",
        order_by="ProcessingLog.created_at",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


# Фрагмент текста документа
class Chunk(Base):
    __tablename__ = "chunk"

    id: Mapped[int] = id_column()
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("document.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)  
    heading: Mapped[str | None] = mapped_column(Text)
    page_from: Mapped[int | None] = mapped_column(Integer)
    page_to: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, nullable=False)

    document: Mapped["Document"] = relationship(back_populates="chunks")


# Курс
class Course(Base):
    __tablename__ = "course"

    id: Mapped[int] = id_column()
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("document.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    goals: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)  
    status: Mapped[CourseStatus] = mapped_column(course_status_enum, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    document: Mapped["Document"] = relationship(back_populates="courses")
    sections: Mapped[list["Section"]] = relationship(
        back_populates="course",
        order_by="Section.position",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


# Раздел курса 
class Section(Base):
    __tablename__ = "section"

    id: Mapped[int] = id_column()
    course_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("course.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    current_version_id: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[SectionStatus] = mapped_column(section_status_enum, nullable=False)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    course: Mapped["Course"] = relationship(back_populates="sections")
    versions: Mapped[list["SectionVersion"]] = relationship(
        back_populates="section",
        order_by="SectionVersion.version_no",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    current_version: Mapped["SectionVersion | None"] = relationship(
        primaryjoin=(
            "and_(foreign(Section.current_version_id) == SectionVersion.id, "
            "Section.id == SectionVersion.section_id)"
        ),
        viewonly=True,
        uselist=False,
    )


# Версия содержимого раздела 
class SectionVersion(Base):
    __tablename__ = "section_version"

    id: Mapped[int] = id_column()
    section_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("section.id", ondelete="CASCADE"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)  
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    author: Mapped[Author] = mapped_column(author_enum, nullable=False)
    model: Mapped[str | None] = mapped_column(Text) 
    prompt_name: Mapped[str | None] = mapped_column(Text)
    user_hint: Mapped[str | None] = mapped_column(Text)
    check_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at_column()

    section: Mapped["Section"] = relationship(back_populates="versions")
    chunks: Mapped[list["Chunk"]] = relationship(
        secondary=section_version_chunk,
        passive_deletes=True,
    )


# Журнал обработки
class ProcessingLog(Base):
    __tablename__ = "processing_log"

    id: Mapped[int] = id_column()
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("document.id", ondelete="CASCADE"), nullable=False
    )
    stage: Mapped[str] = mapped_column(Text, nullable=False)  
    level: Mapped[LogLevel] = mapped_column(log_level_enum, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = created_at_column()

    document: Mapped["Document"] = relationship(back_populates="logs")
