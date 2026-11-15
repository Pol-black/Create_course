from sqlalchemy import select

from app.db import SessionLocal
from app.models import Chunk, Document, DocumentStatus, FileType


def main() -> None:
    with SessionLocal() as session:
        # Создание документа
        doc = Document(
            file_name="test.txt",
            file_type=FileType.TXT,
            file_size=11,
            file_path="/tmp/test.txt",
            status=DocumentStatus.UPLOADED,
            check_enabled=False,
        )
        # Добавление фрагмента через связь
        doc.chunks.append(Chunk(position=0, text="Hello, DB!"))
        session.add(doc)
        session.commit()  
        doc_id = doc.id
        print(f"Создан документ id={doc_id}, created_at={doc.created_at}")

        # Чтение обратно
        session.expunge_all()  
        loaded = session.get(Document, doc_id)
        assert loaded is not None, "Документ не найден"
        print(f"Прочитан: {loaded.file_name}, статус {loaded.status.value}")
        print(f"Фрагмент: {loaded.chunks[0].text!r}")

        # Удаление документа
        session.delete(loaded)
        session.commit()
        left = session.scalars(select(Chunk).where(Chunk.document_id == doc_id)).all()
        assert not left, "Фрагменты не удалились каскадом"
        print("Документ удалён, фрагменты удалены каскадом. Проверка пройдена.")


if __name__ == "__main__":
    main()
