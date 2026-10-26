from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.journal.console import setup_logging
from app.journal.processing_log import log_stage, write_log
from app.models import Document, DocumentStatus, FileType, LogLevel, ProcessingLog


def main() -> None:
    setup_logging(settings.log_level) 

    with SessionLocal() as session:
        # Тестовый документ
        doc = Document(
            file_name="test.txt",
            file_type=FileType.TXT,
            file_size=11,
            file_path="/tmp/test.txt",
            status=DocumentStatus.UPLOADED,
            check_enabled=False,
        )
        session.add(doc)
        session.commit()
        doc_id = doc.id # как еще можно получить

        # Три записи: обычная, успешный этап и этап с ошибкой
        write_log(doc_id, "upload", "Файл загружен")

        with log_stage(doc_id, "extract", "Извлечение текста"):
            sum(range(1000000))  # имитация работы

        try:
            with log_stage(doc_id, "chunk", "Деление на фрагменты"):
                raise ValueError("в тексте нет заголовков")
        except ValueError:
            pass 

        # Чтение журнала из базы
        logs = session.scalars(
            select(ProcessingLog)
            .where(ProcessingLog.document_id == doc_id)
            .order_by(ProcessingLog.id)
        ).all()
        print("\nЖурнал документа из БД:")
        for log in logs:
            print(f"  {log.level.value:5} {log.stage:8} {log.message} ({log.duration_ms} ms)")

        assert [log.level for log in logs] == [LogLevel.INFO, LogLevel.INFO, LogLevel.ERROR]
        assert logs[1].duration_ms is not None, "У этапа нет времени выполнения"

        # Удаление документа
        session.delete(doc)
        session.commit()
        left = session.scalars(
            select(ProcessingLog).where(ProcessingLog.document_id == doc_id)
        ).all()
        assert not left, "Журнал не удалился каскадом"
        print("Документ и журнал удалены. Проверка пройдена.")


if __name__ == "__main__":
    main()